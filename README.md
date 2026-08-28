# RouteIQ — AI Revenue Recovery Agent

RouteIQ is an AI system designed to monitor simulated payment transactions, detect performance drops, investigate root causes, evaluate recovery strategies, and recommend safety-bounded routing modifications.

> [!IMPORTANT]
> **Synthetic Data Disclaimer**: This project uses entirely synthetic transaction data and fictional merchant names for simulation and testing purposes. It does not contain or represent real transaction data or actual provider performance metrics.

---

## Technical Workflow Stages

RouteIQ structures operations into four distinct execution phases:

1.  **DETECTION (Phase 2 & 3)**: SQL aggregation pipelines scan raw transaction logs to detect performance drops.
2.  **INVESTIGATION (Phase 4)**: The stateful AI Payment Risk Analyst agent sequentially executes database tools to isolate the exact degraded segment (Gateway, Method, Bank) and time window.
3.  **RECOVERY SIMULATION (Phase 5)**: Python-bound simulation algorithms compute the potential recovery rates and project remaining risk under alternative routing strategies.
4.  **RECOMMENDATION (Phase 5)**: A composite decision multiplier ranks strategies, and the Gemini agent presents the optimal option to the merchant for human sign-off.

---

## Technical Architecture (Phase 5)

```
routeiq/
├── app/
│   ├── agent/               # Phase 4: Investigation Agent
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   ├── schemas.py
│   │   └── tools.py
│   ├── analytics/           # Phase 2 & 3: Database Analytics Engine
│   │   ├── __init__.py
│   │   ├── investigation.py
│   │   ├── metrics.py
│   │   └── queries.py
│   ├── recovery/            # Phase 5: Recovery & Simulation Engine
│   │   ├── __init__.py      # Exposes run_agent_recovery
│   │   ├── agent.py         # Multi-turn recovery advisor agent
│   │   ├── prompts.py       # Recovery system instructions
│   │   ├── schemas.py       # Pydantic simulation request/response schemas
│   │   ├── simulator.py     # Decimal-safe math libraries
│   │   ├── strategies.py    # Alternative routing, fallback, and retry strategies
│   │   ├── recommendation.py# Heuristic score-based strategy ranking
│   │   └── tools.py         # Read-only simulation wrappers exposed to Gemini
│   ├── db/
│   │   ├── init_db.py
│   │   └── session.py
│   ├── models/
│   │   ├── bank.py
│   │   ├── base.py
│   │   ├── gateway.py
│   │   ├── merchant.py
│   │   ├── payment_method.py
│   │   └── transaction.py
│   ├── data/
│   │   └── generate.py
│   ├── config.py
│   └── main.py
├── tests/
│   ├── test_agent.py
│   ├── test_analytics.py
│   ├── test_data.py
│   ├── test_db.py
│   ├── test_health.py
│   └── test_recovery.py     # New: Recovery strategy & simulation tests
```

---

## Safety & Simulation-Only Boundary

Phase 5 is strictly **simulation-only**. The recovery system has no write permissions:
*   No database mutations (inserts, updates, or deletes on transaction records).
*   No production system configuration changes or payment gateway state modifications.
*   The final response must explicitly contain `"simulation_only": true` and note that no execution has taken place.

---

## Revenue Recovery Methodology

We calculate the potential impact of recovery actions using Decimal-safe math:

$$\text{Current Revenue at Risk} = \text{Baseline Success Rate} \times \text{Attempted Value} - \text{Successful Value}$$

$$\text{Expected Potential Recovery} = \min(\text{Revenue at Risk} \times \text{Estimated Recovery Rate}, \text{Revenue at Risk})$$

$$\text{Remaining Revenue at Risk} = \text{Revenue at Risk} - \text{Expected Potential Recovery}$$

### Recovery Strategies & Assumptions:
1.  **Alternative Gateway Routing** (Data-derived):
    *   Estimates success rate by querying historical transaction logs for alternative gateways servicing the same `(payment_method, bank)` ($N \ge 30$).
    *   Marked as `is_data_derived = true` with `HIGH` confidence.
2.  **Payment Method Fallback** (Data-derived + Switch Assumption):
    *   Queries success rate of other payment methods on the degraded gateway.
    *   Applies a 30% user switch rate assumption (since users must manually enter fallback payment details).
    *   Marked as `is_data_derived = true` with `MEDIUM` confidence.
3.  **Delayed Retry** (Assumption-based):
    *   Lacks historical retry linkage in the database schema.
    *   Applies a flat 20% potential recovery rate assumption for timed-out transactions after the incident resolves.
    *   Marked as `is_data_derived = false` with `LOW` confidence.
4.  **Monitor / No Action** (Baseline):
    *   Zero potential recovery. Represents the cost of taking no intervention.
    *   Marked as `is_data_derived = false` with `HIGH` confidence.

### Strategy Ranking Heuristics:
Strategies are ranked deterministically in Python using a composite scoring heuristic:
$$\text{Score} = \text{expected\_potential\_recovery} \times \text{ConfidenceMultiplier} \times \text{RiskMultiplier}$$
*   *Note: Multipliers are decision-making heuristics to balance reward and operational safety. They are not statistically validated probabilities.*
*   Confidence: `HIGH` = 1.0, `MEDIUM` = 0.8, `LOW` = 0.5.
*   Risk: `LOW` = 1.0, `MEDIUM` = 0.8, `HIGH` = 0.5.

---

## API Endpoints

### 1. Health Liveness
*   **Path**: `GET /health`
*   **Response**: `{"status": "healthy"}`

### 2. Investigation Summary (Phase 3)
*   **Path**: `GET /api/investigation/summary`
*   **Response**: Returns the complete structured deterministic investigation report.

### 3. Agent Investigation (Phase 4)
*   **Path**: `POST /api/agent/investigate`
*   **Payload**: `{"question": "Why are payment success rates declining?"}`

### 4. Agent Recovery Simulation (Phase 5)
*   **Path**: `POST /api/agent/recovery`
*   **Payload**:
    ```json
    {
      "gateway_code": "GATEWAY_D",
      "payment_method_code": "NETBANKING",
      "bank_code": "SBI",
      "attempted_value": 1219053.48,
      "successful_value": 981146.06,
      "baseline_success_rate": 92.12
    }
    ```
*   **Response**:
    ```json
    {
      "status": "complete",
      "simulation_only": true,
      "current_problem": {
        "gateway_code": "GATEWAY_D",
        "payment_method_code": "NETBANKING",
        "bank_code": "SBI",
        "attempted_value": 1219053.48,
        "successful_value": 981146.06,
        "baseline_success_rate": 92.12
      },
      "strategies": [
        {
          "strategy_id": "alternative_gateway",
          "name": "Alternative Gateway Routing",
          "description": "Route affected transactions from GATEWAY_D to alternative gateway GATEWAY_B.",
          "evidence_source": "PostgreSQL table: transactions (alternative gateway: GATEWAY_B)",
          "assumptions": "Assumes routed transactions will achieve the historical success rate of the best alternative gateway (GATEWAY_B) for this segment, which is 91.60%.",
          "is_data_derived": true,
          "estimated_recovery_rate": 0.91595,
          "expected_recovered_revenue": 129924.97,
          "remaining_revenue_at_risk": 11921.04,
          "confidence": "HIGH",
          "risk_level": "LOW"
        }
      ],
      "recommendation": {
        "strategy": "alternative_gateway",
        "expected_recovered_revenue": 129924.97,
        "remaining_revenue_at_risk": 11921.04,
        "confidence": "HIGH",
        "reason": "Strategy 'Alternative Gateway Routing' is recommended as the optimal path. It provides an estimated potential recovery of INR 129,924.97 with a risk level of LOW and confidence of HIGH. This selection is determined by a composite decision heuristic score of 129924.97..."
      },
      "tools_used": [
        "get_recovery_context",
        "simulate_alternative_gateway",
        "simulate_payment_method_fallback",
        "simulate_delayed_retry",
        "simulate_no_action",
        "rank_recovery_strategies"
      ],
      "trace": [...]
    }
    ```

---

## Running Setup & Tests

### 1. Run Database
```bash
docker compose up -d
```

### 2. Initialize Database & Seed
```bash
python -m app.db.init_db --reset
```

### 3. Generate Transactions
```bash
python -m app.data.generate --transactions 50000 --seed 42
```

### 4. Run Test Suite
```bash
pytest -v
```

### 5. Launch API Server
```bash
uvicorn app.main:app --reload
```
