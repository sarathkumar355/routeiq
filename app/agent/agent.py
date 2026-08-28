"""Agent execution loop and tool calling manager."""

import os
import time
import json
from typing import Dict, Any, List
from sqlalchemy.orm import Session
import google.generativeai as genai
from google.generativeai.protos import Part, FunctionResponse, Content

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import (
    get_overall_metrics as get_overall_metrics_impl,
    get_gateway_performance as get_gateway_performance_impl,
    investigate_payment_methods as investigate_payment_methods_impl,
    investigate_banks as investigate_banks_impl,
    investigate_gateway_segments as investigate_gateway_segments_impl,
    investigate_time_patterns as investigate_time_patterns_impl,
    calculate_revenue_at_risk as calculate_revenue_at_risk_impl,
)

MAX_TOOL_CALLS = 10


from app.config import get_settings
from openai import OpenAI

openai_tools = [
    {
        "type": "function",
        "function": {
            "name": "get_overall_metrics",
            "description": "Fetch overall transaction success rates, counts, and financial volumes.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_gateway_performance",
            "description": "Fetch gateway performance metrics ranked by investigation relevance (lowest success rate first).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "investigate_payment_methods",
            "description": "Fetch success rates and attempts grouped by payment method for a specific gateway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_code": {"type": "string", "description": "The unique gateway code to investigate."}
                },
                "required": ["gateway_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "investigate_banks",
            "description": "Fetch success rates and attempts grouped by bank for a specific gateway and payment method.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_code": {"type": "string"},
                    "payment_method_code": {"type": "string"}
                },
                "required": ["gateway_code", "payment_method_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "investigate_gateway_segments",
            "description": "Fetch success rates and volumes grouped by method and bank for a specific gateway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_code": {"type": "string"}
                },
                "required": ["gateway_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "investigate_time_patterns",
            "description": "Fetch hourly success rates and attempt counts for a specific segment to discover window patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_code": {"type": "string"},
                    "payment_method_code": {"type": "string"},
                    "bank_code": {"type": "string"}
                },
                "required": ["gateway_code", "payment_method_code", "bank_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_revenue_at_risk",
            "description": "Calculate the estimated transaction value lost during an incident window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attempted_value": {"type": "number"},
                    "successful_value": {"type": "number"},
                    "baseline_success_rate": {"type": "number"}
                },
                "required": ["attempted_value", "successful_value", "baseline_success_rate"]
            }
        }
    }
]


def run_openrouter_investigation(db: Session, question: str, api_key: str) -> Dict[str, Any]:
    """Execute OpenRouter stateful manual tool calling loop for investigation."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

    def get_overall_metrics() -> Dict[str, Any]:
        return get_overall_metrics_impl(db)

    def get_gateway_performance() -> List[Dict[str, Any]]:
        return get_gateway_performance_impl(db)

    def investigate_payment_methods(gateway_code: str) -> List[Dict[str, Any]]:
        return investigate_payment_methods_impl(db, gateway_code)

    def investigate_banks(gateway_code: str, payment_method_code: str) -> List[Dict[str, Any]]:
        return investigate_banks_impl(db, gateway_code, payment_method_code)

    def investigate_gateway_segments(gateway_code: str) -> List[Dict[str, Any]]:
        return investigate_gateway_segments_impl(db, gateway_code)

    def investigate_time_patterns(
        gateway_code: str, payment_method_code: str, bank_code: str
    ) -> List[Dict[str, Any]]:
        return investigate_time_patterns_impl(db, gateway_code, payment_method_code, bank_code)

    def calculate_revenue_at_risk(
        attempted_value: float, successful_value: float, baseline_success_rate: float
    ) -> Dict[str, Any]:
        return calculate_revenue_at_risk_impl(attempted_value, successful_value, baseline_success_rate)

    tools_map = {
        "get_overall_metrics": get_overall_metrics,
        "get_gateway_performance": get_gateway_performance,
        "investigate_payment_methods": investigate_payment_methods,
        "investigate_banks": investigate_banks,
        "investigate_gateway_segments": investigate_gateway_segments,
        "investigate_time_patterns": investigate_time_patterns,
        "calculate_revenue_at_risk": calculate_revenue_at_risk,
    }

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]
    tools_used = []
    investigation_trace = []
    calls_count = 0
    limit_reached = False

    while calls_count < MAX_TOOL_CALLS:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=messages,
            tools=openai_tools,
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
            
            investigation_trace.append({
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
            "investigation report JSON based on the evidence collected so far. Indicate in the "
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
            "status": "failed",
            "summary": "AI Agent failed to produce a valid JSON report.",
            "severity": "medium",
            "root_cause": {
                "gateway": None,
                "payment_method": None,
                "bank": None,
                "time_window": None,
                "dates": []
            },
            "evidence": [],
            "baseline_success_rate": 0.0,
            "affected_success_rate": 0.0,
            "rate_drop": 0.0,
            "sample_size": 0,
            "estimated_revenue_at_risk": 0.0,
            "confidence": "LOW",
            "tools_used": tools_used
        }
        
    return {
        "status": "complete" if not limit_reached else "limit_reached",
        "report": report,
        "tools_used": tools_used,
        "investigation_trace": investigation_trace
    }


def run_agent_investigation(db: Session, question: str) -> Dict[str, Any]:
    """Execute the AI Agent investigation loop step-by-step.

    Args:
        db: Database session.
        question: User prompt query.

    Returns:
        Dict containing status, report, tools_used list, and investigation_trace.
    """
    settings = get_settings()
    openrouter_key = settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
    is_testing = "PYTEST_CURRENT_TEST" in os.environ
    if openrouter_key and not is_testing:
        return run_openrouter_investigation(db, question, openrouter_key)

    # 1. Verify API Key presence
    api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Neither OPENROUTER_API_KEY nor GEMINI_API_KEY is configured.")

    # 2. Configure Gemini SDK
    genai.configure(api_key=api_key)

    # 3. Create Session-bound tool wrappers
    def get_overall_metrics() -> Dict[str, Any]:
        """Fetch overall transaction success rates, counts, and financial volumes."""
        return get_overall_metrics_impl(db)

    def get_gateway_performance() -> List[Dict[str, Any]]:
        """Fetch gateway performance metrics ranked by investigation relevance (lowest success rate first)."""
        return get_gateway_performance_impl(db)

    def investigate_payment_methods(gateway_code: str) -> List[Dict[str, Any]]:
        """Fetch success rates and attempts grouped by payment method for a specific gateway."""
        return investigate_payment_methods_impl(db, gateway_code)

    def investigate_banks(gateway_code: str, payment_method_code: str) -> List[Dict[str, Any]]:
        """Fetch success rates and attempts grouped by bank for a specific gateway and payment method."""
        return investigate_banks_impl(db, gateway_code, payment_method_code)

    def investigate_gateway_segments(gateway_code: str) -> List[Dict[str, Any]]:
        """Fetch success rates and volumes grouped by method and bank for a specific gateway."""
        return investigate_gateway_segments_impl(db, gateway_code)

    def investigate_time_patterns(
        gateway_code: str, payment_method_code: str, bank_code: str
    ) -> List[Dict[str, Any]]:
        """Fetch hourly success rates and attempt counts for a specific segment to discover window patterns."""
        return investigate_time_patterns_impl(db, gateway_code, payment_method_code, bank_code)

    def calculate_revenue_at_risk(
        attempted_value: float, successful_value: float, baseline_success_rate: float
    ) -> Dict[str, Any]:
        """Calculate the estimated transaction value lost during an incident window."""
        return calculate_revenue_at_risk_impl(attempted_value, successful_value, baseline_success_rate)

    tools_list = [
        get_overall_metrics,
        get_gateway_performance,
        investigate_payment_methods,
        investigate_banks,
        investigate_gateway_segments,
        investigate_time_patterns,
        calculate_revenue_at_risk,
    ]

    tools_map = {t.__name__: t for t in tools_list}

    # Initialize model
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT
    )

    # Initialize execution trace and state
    messages = [{"role": "user", "parts": [question]}]
    tools_used = []
    investigation_trace = []
    calls_count = 0
    limit_reached = False

    while calls_count < MAX_TOOL_CALLS:
        # Call model with current state and tools registry
        response = model.generate_content(messages, tools=tools_list)
        
        # Capture candidate content and append to history
        content = response.candidates[0].content
        messages.append(content)

        # Check for function/tool calls in parts
        function_calls = [p.function_call for p in content.parts if p.function_call]
        if not function_calls:
            # Model has generated text and did not invoke any more tools
            break

        # Execute requested tools
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

            # Record development trace trace logs (secrets omitted)
            investigation_trace.append({
                "tool_name": tool_name,
                "arguments": tool_args,
                "status": status,
                "execution_duration_sec": round(duration, 4),
                "result_summary": str(result)[:300]
            })

            # Format result body safely
            if isinstance(result, list):
                response_body = {"result": result}
            elif isinstance(result, dict):
                response_body = result
            else:
                response_body = {"result": result}

            # Construct Protobuf-safe FunctionResponse part
            part = Part(
                function_response=FunctionResponse(
                    name=tool_name,
                    response=response_body
                )
            )
            function_responses.append(part)

        if limit_reached:
            break

        # Append function response turn to history
        messages.append(Content(
            role="user",
            parts=function_responses
        ))

    # Determine if we were interrupted by the limit before the model could return a text report.
    # The loop exits either when no function calls are returned, or when calls_count >= MAX_TOOL_CALLS.
    # If the last message is a user function response, it means we interrupted the loop.
    last_msg = messages[-1]
    last_role = last_msg.get("role") if isinstance(last_msg, dict) else getattr(last_msg, "role", None)
    if last_role == "user":
        limit_reached = True

    # If the tool calls limit was reached, prompt model to generate a summary of current findings
    if limit_reached:
        prompt_limit = (
            "The maximum tool-call limit of 10 was reached. Please synthesize the final "
            "investigation report JSON based on the evidence collected so far. Indicate in the "
            "summary that the tool-call limit was reached."
        )
        messages.append({"role": "user", "parts": [prompt_limit]})
        final_res = model.generate_content(messages)
        response_text = final_res.text
    else:
        # Get final text response from the last content part in the loop
        response_text = response.text

    # Parse JSON report safely by cleaning potential markdown code blocks first
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
            "status": "failed",
            "summary": "AI Agent failed to produce a valid JSON report.",
            "severity": "medium",
            "root_cause": {
                "gateway": None,
                "payment_method": None,
                "bank": None,
                "time_window": None,
                "dates": []
            },
            "evidence": [],
            "baseline_success_rate": 0.0,
            "affected_success_rate": 0.0,
            "rate_drop": 0.0,
            "sample_size": 0,
            "estimated_revenue_at_risk": 0.0,
            "confidence": "LOW",
            "tools_used": tools_used
        }

    return {
        "status": "complete" if not limit_reached else "limit_reached",
        "report": report,
        "tools_used": tools_used,
        "investigation_trace": investigation_trace
    }
