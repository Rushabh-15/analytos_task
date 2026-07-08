"""Typed contract between the LLM extraction step and the graph mapper.

The LLM must emit JSON matching ExtractionResult. Pydantic validates it;
anything malformed fails the run loudly instead of loading garbage.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class XProduct(_Base):
    name: str
    tagline: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    stage: Optional[Literal["live", "pilot", "beta", "concept"]] = None
    website: Optional[str] = None


class XFeature(_Base):
    product: str
    name: str
    description: Optional[str] = None
    differentiator: Optional[bool] = None


class XProofPoint(_Base):
    product: str
    feature: Optional[str] = None
    claim: str
    metric_name: Optional[str] = None
    metric_value: Optional[str] = None
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    timeframe: Optional[str] = None
    evidence_type: Optional[Literal[
        "pilot_result", "benchmark", "customer_quote",
        "case_study", "internal_estimate"]] = None
    context: Optional[str] = None
    client_safe: bool = True


class XSegment(_Base):
    name: str
    description: Optional[str] = None
    industries: List[str] = Field(default_factory=list)
    company_size: Optional[str] = None
    geographies: List[str] = Field(default_factory=list)
    tech_stack_signals: List[str] = Field(default_factory=list)
    trigger_signals: List[str] = Field(default_factory=list)
    pain_points: List[str] = Field(default_factory=list)
    disqualifiers: List[str] = Field(default_factory=list)
    target_products: List[str] = Field(default_factory=list)


class XPersona(_Base):
    segment: Optional[str] = None
    title: str
    seniority: Optional[str] = None
    department: Optional[str] = None
    buying_role: Optional[Literal[
        "champion", "economic_buyer", "end_user", "influencer", "blocker"]] = None
    goals: List[str] = Field(default_factory=list)
    pain_points: List[str] = Field(default_factory=list)
    objections: List[str] = Field(default_factory=list)


class XCompetitor(_Base):
    product: str
    name: str
    notes: Optional[str] = None
    displacement_angle: Optional[str] = None


class XPerson(_Base):
    name: str
    email: Optional[str] = None
    org: Optional[str] = None
    role: Optional[str] = None
    is_internal: Optional[bool] = None


class XDecision(_Base):
    summary: str
    status: Optional[Literal["decided", "proposed", "revisited", "rejected"]] = None
    decided_at: Optional[str] = None          # ISO datetime
    rationale: Optional[str] = None
    products: List[str] = Field(default_factory=list)
    decided_by: List[str] = Field(default_factory=list)   # person names


class XMessage(_Base):
    seq: int
    sender: str                                # email address preferred
    recipients: List[str] = Field(default_factory=list)
    sent_at: Optional[str] = None              # ISO datetime
    body: str


class XThread(_Base):
    subject: str
    summary: Optional[str] = None
    internal_only: bool = True
    started_at: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    product_refs: List[str] = Field(default_factory=list)   # product names
    messages: List[XMessage] = Field(default_factory=list)


class ExtractionResult(_Base):
    doc_type: Literal["product_doc", "icp_doc", "email_thread", "other"]
    title: Optional[str] = None
    products: List[XProduct] = Field(default_factory=list)
    features: List[XFeature] = Field(default_factory=list)
    proof_points: List[XProofPoint] = Field(default_factory=list)
    segments: List[XSegment] = Field(default_factory=list)
    personas: List[XPersona] = Field(default_factory=list)
    competitors: List[XCompetitor] = Field(default_factory=list)
    people: List[XPerson] = Field(default_factory=list)
    decisions: List[XDecision] = Field(default_factory=list)
    thread: Optional[XThread] = None
