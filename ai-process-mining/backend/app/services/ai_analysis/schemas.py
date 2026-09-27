"""Structured AI output. The LLM cites fact ids; the server fills in the actual values."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMFinding(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=1500)
    evidence_fact_ids: list[str] = Field(min_length=1, max_length=8)
    severity: Literal["low", "medium", "high"]
    possible_explanations: list[str] = Field(default_factory=list, max_length=6)
    recommended_investigations: list[str] = Field(default_factory=list, max_length=6)


class LLMReport(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    key_findings: list[LLMFinding] = Field(min_length=1, max_length=10)
    data_quality_notes: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    additional_data_suggestions: list[str] = Field(default_factory=list, max_length=10)


class Evidence(BaseModel):
    fact_id: str
    metric: str
    value: str


class Drilldown(BaseModel):
    kind: Literal["activity", "transition", "deviation", "variant", "overview", "resource"]
    activity: str | None = None
    source: str | None = None
    target: str | None = None
    deviation_type: str | None = None
    variant_id: str | None = None
    resource: str | None = None


class Finding(BaseModel):
    title: str
    description: str
    evidence: list[Evidence]
    severity: Literal["low", "medium", "high"]
    possible_explanations: list[str] = []
    recommended_investigations: list[str] = []
    drilldown: Drilldown | None = None


class AnalysisReport(BaseModel):
    summary: str
    key_findings: list[Finding]
    data_quality_notes: list[str] = []
    limitations: list[str] = []
    additional_data_suggestions: list[str] = []
    guardrail_flags: list[str] = []
    generated_by: dict = {}


REPORT_TOOL = {
    "name": "submit_report",
    "description": "Submit the process analysis report. Every finding must cite fact ids from the provided facts.",
    "input_schema": {
        "type": "object",
        "required": ["summary", "key_findings", "data_quality_notes", "limitations"],
        "properties": {
            "summary": {"type": "string", "description": "3-5 sentences: what is happening in the process."},
            "key_findings": {
                "type": "array", "minItems": 1, "maxItems": 8,
                "items": {
                    "type": "object",
                    "required": ["title", "description", "evidence_fact_ids", "severity",
                                 "possible_explanations", "recommended_investigations"],
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string", "description": "Observed facts only. No causal claims."},
                        "evidence_fact_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "possible_explanations": {"type": "array", "items": {"type": "string"},
                                                  "description": "Hypotheses to investigate, phrased as possibilities."},
                        "recommended_investigations": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "data_quality_notes": {"type": "array", "items": {"type": "string"}},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "additional_data_suggestions": {"type": "array", "items": {"type": "string"}},
        },
    },
}
