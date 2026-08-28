"""Recovery strategy agent execution loop and tool calling manager."""

import os
import time
import json
from typing import Dict, Any, List
from sqlalchemy.orm import Session
import google.generativeai as genai
from google.generativeai.protos import Part, FunctionResponse, Content

from app.recovery.prompts import SYSTEM_PROMPT
from app.recovery.schemas import RecoverySimulationRequest
from app.recovery.tools import (
    get_recovery_context as get_recovery_context_impl,
    simulate_alternative_gateway as simulate_alternative_gateway_impl,
    simulate_payment_method_fallback as simulate_payment_method_fallback_impl,
    simulate_delayed_retry as simulate_delayed_retry_impl,
    simulate_no_action as simulate_no_action_impl,
    rank_recovery_strategies as rank_recovery_strategies_impl,
)

MAX_TOOL_CALLS = 10


from app.config import get_settings
from openai import OpenAI

openai_recovery_tools = [
    {
        "type": "function",
        "function": {
            "name": "get_recovery_context",
            "description": "Fetch database metrics for the incident segment and potential alternatives.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_alternative_gateway",
            "description": "Simulate routing affected transactions to the best available alternative gateway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "revenue_at_risk": {"type": "number", "description": "The current revenue at risk to simulate against."}
                },
                "required": ["revenue_at_risk"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_payment_method_fallback",
            "description": "Simulate switching transactions to the best alternative payment method on the same gateway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "revenue_at_risk": {"type": "number", "description": "The current revenue at risk to simulate against."}
                },
                "required": ["revenue_at_risk"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_delayed_retry",
            "description": "Simulate retrying failed transactions after the degradation window resolves (assumption-based).",
            "parameters": {
                "type": "object",
                "properties": {
                    "revenue_at_risk": {"type": "number", "description": "The current revenue at risk to simulate against."}
                },
                "required": ["revenue_at_risk"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_no_action",
            "description": "Baseline strategy representing the scenario of taking no recovery actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "revenue_at_risk": {"type": "number", "description": "The current revenue at risk to simulate against."}
                },
                "required": ["revenue_at_risk"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rank_recovery_strategies",
            "description": "Rank all simulated strategies and return the recommended option.",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategies": {
                        "type": "array",
                        "items": {
                            "type": "object"
                        },
                        "description": "List of simulated strategies to rank."
                    }
                },
                "required": ["strategies"]
            }
        }
    }
]


def run_openrouter_recovery(db: Session, payload: RecoverySimulationRequest, api_key: str) -> Dict[str, Any]:
    """Execute OpenRouter recovery strategy simulation loop."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

    def get_recovery_context() -> Dict[str, Any]:
        return get_recovery_context_impl(
            db, payload.gateway_code, payload.payment_method_code, payload.bank_code
        )

    def simulate_alternative_gateway(revenue_at_risk: float) -> Dict[str, Any]:
        return simulate_alternative_gateway_impl(
            db, payload.gateway_code, payload.payment_method_code, payload.bank_code, revenue_at_risk
        )

    def simulate_payment_method_fallback(revenue_at_risk: float) -> Dict[str, Any]:
        return simulate_payment_method_fallback_impl(
            db, payload.gateway_code, payload.payment_method_code, payload.bank_code, revenue_at_risk
        )

    def simulate_delayed_retry(revenue_at_risk: float) -> Dict[str, Any]:
        return simulate_delayed_retry_impl(revenue_at_risk)

    def simulate_no_action(revenue_at_risk: float) -> Dict[str, Any]:
        return simulate_no_action_impl(revenue_at_risk)

    def rank_recovery_strategies(strategies: List[Dict[str, Any]]) -> Dict[str, Any]:
        return rank_recovery_strategies_impl(strategies)

    tools_map = {
        "get_recovery_context": get_recovery_context,
        "simulate_alternative_gateway": simulate_alternative_gateway,
        "simulate_payment_method_fallback": simulate_payment_method_fallback,
        "simulate_delayed_retry": simulate_delayed_retry,
        "simulate_no_action": simulate_no_action,
        "rank_recovery_strategies": rank_recovery_strategies,
    }

    question = (
        f"Please run a recovery strategy simulation and recommend the optimal recovery plan for the following incident segment: "
        f"Gateway: {payload.gateway_code}, Payment Method: {payload.payment_method_code}, Bank: {payload.bank_code}. "
        f"Metrics inside degradation window: Attempted Value: INR {payload.attempted_value:.2f}, "
        f"Successful Value: INR {payload.successful_value:.2f}, Baseline Success Rate: {payload.baseline_success_rate:.2f}%."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]
    tools_used = []
    trace = []
    calls_count = 0
    limit_reached = False

    while calls_count < MAX_TOOL_CALLS:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=messages,
            tools=openai_recovery_tools,
            tool_choice="auto",
            max_tokens=2000
        )
        
        response_message = response.choices[0].message
        messages.append(response_message)
        
        tool_calls = response_message.tool_calls
        if not tool_calls:
            response_text = response_message.content or ""
            break
            
        for tool_call in tool_calls:
            calls_count += 1
            if calls_count > MAX_TOOL_CALLS:
                limit_reached = True
                break
                
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            tools_used.append(tool_name)
            
            start_time = time.time()
            try:
                if tool_name in tools_map:
                    result = tools_map[tool_name](**tool_args)
                    status = "success"
                else:
                    result = {"error": f"Tool '{tool_name}' not found."}
                    status = "failed"
            except Exception as e:
                result = {"error": str(e)}
                status = "failed"
            duration = time.time() - start_time
            
            trace.append({
                "tool_name": tool_name,
                "arguments": tool_args,
                "status": status,
                "execution_duration_sec": round(duration, 4),
                "result_summary": str(result)[:300]
            })
            
            if isinstance(result, list):
                response_body = {"result": result}
            elif isinstance(result, dict):
                response_body = result
            else:
                response_body = {"result": result}
                
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(response_body)
            })
            
        if limit_reached:
            break
            
    if limit_reached:
        prompt_limit = (
            "The maximum tool-call limit of 10 was reached. Please synthesize the final "
            "recovery report JSON based on the evidence collected so far. Indicate in the "
            "summary that the tool-call limit was reached."
        )
        messages.append({"role": "user", "content": prompt_limit})
        final_res = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=messages,
            max_tokens=2000
        )
        response_text = final_res.choices[0].message.content or ""
    else:
        response_text = response_message.content or ""
        
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        lines = cleaned_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned_text = "\n".join(lines).strip()
        
    try:
        report = json.loads(cleaned_text)
    except Exception:
        report = {
            "current_revenue_at_risk": 0.0,
            "strategies": [],
            "recommended_strategy": "no_action",
            "recommendation_reason": "AI Agent failed to produce a valid JSON report.",
            "confidence": "LOW"
        }
        
    recommended_id = report.get("recommended_strategy", "no_action")
    recommended_strategy = None
    for s in report.get("strategies", []):
        if s.get("strategy_id") == recommended_id:
            recommended_strategy = s
            break

    expected_rec = 0.0
    remaining_risk = 0.0
    if recommended_strategy:
        expected_rec = float(recommended_strategy.get("expected_recovered_revenue", 0.0))
        remaining_risk = float(recommended_strategy.get("remaining_revenue_at_risk", 0.0))

    return {
        "status": "complete" if not limit_reached else "limit_reached",
        "simulation_only": True,
        "current_problem": {
            "gateway_code": payload.gateway_code,
            "payment_method_code": payload.payment_method_code,
            "bank_code": payload.bank_code,
            "attempted_value": payload.attempted_value,
            "successful_value": payload.successful_value,
            "baseline_success_rate": payload.baseline_success_rate
        },
        "strategies": report.get("strategies", []),
        "recommendation": {
            "strategy": recommended_id,
            "expected_recovered_revenue": expected_rec,
            "remaining_revenue_at_risk": remaining_risk,
            "confidence": report.get("confidence", "LOW"),
            "reason": report.get("recommendation_reason", "Fallback recommendation due to parsing error.")
        },
        "tools_used": tools_used,
        "trace": trace
    }


def run_agent_recovery(db: Session, payload: RecoverySimulationRequest) -> Dict[str, Any]:
    """Execute the AI Agent recovery strategy simulation loop.

    Args:
        db: Database session.
        payload: Incident details and metrics.

    Returns:
        Dict containing status, strategies list, recommended strategy recommendation, tools_used, and trace.
    """
    settings = get_settings()
    openrouter_key = settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
    is_testing = "PYTEST_CURRENT_TEST" in os.environ
    if openrouter_key and not is_testing:
        return run_openrouter_recovery(db, payload, openrouter_key)

    # 1. Verify API Key presence
    api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Neither OPENROUTER_API_KEY nor GEMINI_API_KEY is configured.")

    # 2. Configure Gemini SDK
    genai.configure(api_key=api_key)

    # 3. Create Session-bound tool wrappers matching exact runtime names
    def get_recovery_context() -> Dict[str, Any]:
        """Fetch database metrics for the incident segment and potential alternatives."""
        return get_recovery_context_impl(
            db, payload.gateway_code, payload.payment_method_code, payload.bank_code
        )

    def simulate_alternative_gateway(revenue_at_risk: float) -> Dict[str, Any]:
        """Simulate routing affected transactions to the best available alternative gateway."""
        return simulate_alternative_gateway_impl(
            db, payload.gateway_code, payload.payment_method_code, payload.bank_code, revenue_at_risk
        )

    def simulate_payment_method_fallback(revenue_at_risk: float) -> Dict[str, Any]:
        """Simulate switching transactions to the best alternative payment method on the same gateway."""
        return simulate_payment_method_fallback_impl(
            db, payload.gateway_code, payload.payment_method_code, payload.bank_code, revenue_at_risk
        )

    def simulate_delayed_retry(revenue_at_risk: float) -> Dict[str, Any]:
        """Simulate retrying failed transactions after the degradation window resolves (assumption-based)."""
        return simulate_delayed_retry_impl(revenue_at_risk)

    def simulate_no_action(revenue_at_risk: float) -> Dict[str, Any]:
        """Baseline strategy representing the scenario of taking no recovery actions."""
        return simulate_no_action_impl(revenue_at_risk)

    def rank_recovery_strategies(strategies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Rank all simulated strategies and return the recommended option."""
        return rank_recovery_strategies_impl(strategies)

    tools_list = [
        get_recovery_context,
        simulate_alternative_gateway,
        simulate_payment_method_fallback,
        simulate_delayed_retry,
        simulate_no_action,
        rank_recovery_strategies,
    ]

    tools_map = {t.__name__: t for t in tools_list}

    # Initialize model
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT
    )

    # Initialize execution trace and state
    question = (
        f"Please run a recovery strategy simulation and recommend the optimal recovery plan for the following incident segment: "
        f"Gateway: {payload.gateway_code}, Payment Method: {payload.payment_method_code}, Bank: {payload.bank_code}. "
        f"Metrics inside degradation window: Attempted Value: INR {payload.attempted_value:.2f}, "
        f"Successful Value: INR {payload.successful_value:.2f}, Baseline Success Rate: {payload.baseline_success_rate:.2f}%."
    )

    messages = [{"role": "user", "parts": [question]}]
    tools_used = []
    trace = []
    calls_count = 0
    limit_reached = False

    while calls_count < MAX_TOOL_CALLS:
        response = model.generate_content(messages, tools=tools_list)
        content = response.candidates[0].content
        messages.append(content)

        function_calls = [p.function_call for p in content.parts if p.function_call]
        if not function_calls:
            break

        function_responses = []
        for call in function_calls:
            calls_count += 1
            if calls_count > MAX_TOOL_CALLS:
                limit_reached = True
                break

            tool_name = call.name
            tool_args = dict(call.args)
            tools_used.append(tool_name)

            start_time = time.time()
            try:
                if tool_name in tools_map:
                    result = tools_map[tool_name](**tool_args)
                    status = "success"
                else:
                    result = {"error": f"Tool '{tool_name}' not found."}
                    status = "failed"
            except Exception as e:
                result = {"error": str(e)}
                status = "failed"
            duration = time.time() - start_time

            trace.append({
                "tool_name": tool_name,
                "arguments": tool_args,
                "status": status,
                "execution_duration_sec": round(duration, 4),
                "result_summary": str(result)[:300]
            })

            # Format result payload
            if isinstance(result, list):
                response_body = {"result": result}
            elif isinstance(result, dict):
                response_body = result
            else:
                response_body = {"result": result}

            part = Part(
                function_response=FunctionResponse(
                    name=tool_name,
                    response=response_body
                )
            )
            function_responses.append(part)

        if limit_reached:
            break

        messages.append(Content(
            role="user",
            parts=function_responses
        ))

    # Interrupt if limit reached
    last_msg = messages[-1]
    last_role = last_msg.get("role") if isinstance(last_msg, dict) else getattr(last_msg, "role", None)
    if last_role == "user":
        limit_reached = True

    if limit_reached:
        prompt_limit = (
            "The maximum tool-call limit of 10 was reached. Please synthesize the final "
            "recovery strategy recommendation JSON based on the evidence collected so far."
        )
        messages.append({"role": "user", "parts": [prompt_limit]})
        final_res = model.generate_content(messages)
        response_text = final_res.text
    else:
        response_text = response.text

    # Parse JSON report safely by cleaning potential markdown code blocks
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        lines = cleaned_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned_text = "\n".join(lines).strip()

    try:
        report = json.loads(cleaned_text)
    except Exception:
        # Fallback structured report if JSON parsing fails
        report = {
            "current_revenue_at_risk": 0.0,
            "strategies": [],
            "recommended_strategy": "no_action",
            "recommendation_reason": "AI Agent failed to produce a valid JSON report.",
            "confidence": "LOW"
        }

    recommended_id = report.get("recommended_strategy", "no_action")
    recommended_strategy = None
    for s in report.get("strategies", []):
        if s.get("strategy_id") == recommended_id:
            recommended_strategy = s
            break

    expected_rec = 0.0
    remaining_risk = 0.0
    if recommended_strategy:
        expected_rec = float(recommended_strategy.get("expected_recovered_revenue", 0.0))
        remaining_risk = float(recommended_strategy.get("remaining_revenue_at_risk", 0.0))

    # Extract sub-fields matching API spec
    return {
        "status": "complete" if not limit_reached else "limit_reached",
        "simulation_only": True,
        "current_problem": {
            "gateway_code": payload.gateway_code,
            "payment_method_code": payload.payment_method_code,
            "bank_code": payload.bank_code,
            "attempted_value": payload.attempted_value,
            "successful_value": payload.successful_value,
            "baseline_success_rate": payload.baseline_success_rate
        },
        "strategies": report.get("strategies", []),
        "recommendation": {
            "strategy": recommended_id,
            "expected_recovered_revenue": expected_rec,
            "remaining_revenue_at_risk": remaining_risk,
            "confidence": report.get("confidence", "LOW"),
            "reason": report.get("recommendation_reason", "Fallback recommendation due to parsing error.")
        },
        "tools_used": tools_used,
        "trace": trace
    }
