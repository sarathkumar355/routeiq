"""Pydantic schemas for Agentic AI Layer request and response validation."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class InvestigationRequest(BaseModel):
    """Schema for POST /api/agent/investigate request payload."""

    question: Optional[str] = Field(
        default="Why are payment success rates declining?",
        description="The investigation prompt or query for the Payment Risk Investigation Analyst.",
    )


class RootCause(BaseModel):
    """Details of the verified root cause segment and window."""

    gateway: Optional[str] = None
    payment_method: Optional[str] = None
    bank: Optional[str] = None
    time_window: Optional[str] = None
    dates: Optional[List[str]] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """An individual quantitative observation extracted from deterministic tools."""

    observation: str
    value: str
    source_tool: str


class InvestigationReport(BaseModel):
    """Validated structured final report produced by the agent."""

    status: str = Field(..., description="E.g., 'complete' or 'failed'")
    summary: str = Field(..., description="Concise human-readable evidence summary")
    severity: str = Field(..., description="E.g., 'low', 'medium', or 'high'")
    root_cause: RootCause
    evidence: List[EvidenceItem] = Field(default_factory=list)
    baseline_success_rate: Optional[float] = None
    affected_success_rate: Optional[float] = None
    rate_drop: Optional[float] = None
    sample_size: Optional[int] = None
    estimated_revenue_at_risk: Optional[float] = None
    confidence: str = Field(..., description="Qualitative confidence: 'LOW', 'MEDIUM', or 'HIGH'")
    tools_used: List[str] = Field(default_factory=list)


class InvestigationResponse(BaseModel):
    """Schema for POST /api/agent/investigate response body."""

    status: str = Field(..., description="Status of the agent execution loop.")
    report: Dict[str, Any] = Field(..., description="The structured final investigation report.")
    tools_used: List[str] = Field(default_factory=list, description="List of tools invoked in order.")
    investigation_trace: List[Dict[str, Any]] = Field(
        default_factory=list, description="Trace of all tool-call metadata for development/debugging."
    )
