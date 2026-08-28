"""
FastAPI application entry point.

Phase 1 scope: just the app instance and a /health endpoint. Every later
phase (routing simulation, agent, ML, etc.) will register its own routers
here — nothing else is wired up yet on purpose.
"""

from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from dotenv import load_dotenv
load_dotenv(override=True)

from app.config import get_settings
from app.db.session import get_db_session
from app.analytics import run_investigation
from app.agent import run_agent_investigation
from app.agent.schemas import InvestigationRequest, InvestigationResponse
from app.recovery import run_agent_recovery
from app.recovery.schemas import RecoverySimulationRequest, RecoveryRecommendationResponse

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="AI Revenue Recovery Agent for payment failure investigation and recovery.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Liveness check. Intentionally has zero dependencies (no DB, no AI key)
    so it always reflects whether the API process itself is up."""
    return {"status": "healthy"}


def get_db():
    with get_db_session() as db:
        yield db


@app.get("/api/investigation/summary")
def get_investigation_summary(db: Session = Depends(get_db)) -> dict:
    """Execute the root-cause investigation engine and return findings."""
    return run_investigation(db)


@app.post("/api/agent/investigate", response_model=InvestigationResponse)
def post_agent_investigate(
    payload: Optional[InvestigationRequest] = None,
    db: Session = Depends(get_db)
) -> dict:
    """Run the stateful AI Payment Risk Analyst agent loop on transaction data."""
    import os
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        raise HTTPException(
            status_code=503,
            detail="AI API Key (OPENROUTER_API_KEY or GEMINI_API_KEY) is not configured."
        )

    question = "Why are payment success rates declining?"
    if payload and payload.question:
        question = payload.question

    try:
        result = run_agent_investigation(db, question)
        return result
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent failed: {str(e)}")


@app.post("/api/agent/recovery", response_model=RecoveryRecommendationResponse)
def post_agent_recovery(
    payload: RecoverySimulationRequest,
    db: Session = Depends(get_db)
) -> dict:
    """Run the stateful AI Payment Recovery Strategy Advisor agent loop."""
    import os
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        raise HTTPException(
            status_code=503,
            detail="AI API Key (OPENROUTER_API_KEY or GEMINI_API_KEY) is not configured."
        )

    try:
        result = run_agent_recovery(db, payload)
        return result
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent failed: {str(e)}")
