"""Pydantic models for RouteIQ Phase 5 Recovery Strategy & Revenue Recovery Simulation."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class RecoveryStrategy(BaseModel):
    """Details of a simulated recovery strategy and its estimated outcomes."""

    strategy_id: str = Field(..., description="Unique identifier for the strategy, e.g. alternative_gateway")
    name: str = Field(..., description="Human-readable name of the strategy")
    description: str = Field(..., description="Brief description of the strategy concept")
    evidence_source: str = Field(..., description="Data source or basis of the evidence used")
    assumptions: str = Field(..., description="Explicitly documented assumptions for the simulation")
    is_data_derived: bool = Field(..., description="True if based on historical database stats, False if assumption-based")
    estimated_recovery_rate: float = Field(..., description="Estimated percentage rate of recovery (0.0 to 1.0)")
    expected_recovered_revenue: float = Field(..., description="Estimated potential recovery in INR")
    remaining_revenue_at_risk: float = Field(..., description="Remaining revenue at risk after recovery in INR")
    confidence: str = Field(..., description="Qualitative confidence rating: LOW, MEDIUM, or HIGH")
    risk_level: str = Field(..., description="Qualitative risk rating: LOW, MEDIUM, or HIGH")


class RecoverySimulationRequest(BaseModel):
    """Schema for POST /api/agent/recovery request payload."""

    gateway_code: str = Field(..., description="Degraded gateway code")
    payment_method_code: str = Field(..., description="Degraded payment method code")
    bank_code: str = Field(..., description="Degraded bank code")
    attempted_value: float = Field(..., description="Total attempted transaction value inside degradation window")
    successful_value: float = Field(..., description="Total successful transaction value inside degradation window")
    baseline_success_rate: float = Field(..., description="Baseline success rate (percentage, e.g. 92.89) outside window")


class RecoverySimulationResult(BaseModel):
    """Results of executing the deterministic recovery simulation and ranking engine."""

    current_revenue_at_risk: float = Field(..., description="Calculated initial revenue at risk in INR")
    strategies: List[RecoveryStrategy] = Field(default_factory=list, description="List of all simulated strategies")
    recommended_strategy: str = Field(..., description="The ID of the recommended strategy")
    recommendation_reason: str = Field(..., description="Deterministic reason explaining why this strategy was chosen")
    confidence: str = Field(..., description="Overall confidence level of the recommendation")


class RecoveryRecommendationResponse(BaseModel):
    """Schema for POST /api/agent/recovery response body."""

    status: str = Field(..., description="Status of the agent recovery execution: e.g. complete or failed")
    simulation_only: bool = Field(default=True, description="Safety flag confirming no live payments or changes were run")
    current_problem: Dict[str, Any] = Field(..., description="Context of the incident being addressed")
    strategies: List[RecoveryStrategy] = Field(default_factory=list, description="Details of all simulated options")
    recommendation: Dict[str, Any] = Field(..., description="The recommended action details")
    tools_used: List[str] = Field(default_factory=list, description="List of tools invoked in order")
    trace: List[Dict[str, Any]] = Field(default_factory=list, description="Chronological trace of recovery tool runs")
