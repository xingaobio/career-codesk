from __future__ import annotations

from typing import Any, Dict


GUIDE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "decision",
        "summary",
        "implementation_steps",
        "risks",
        "acceptance_checks",
        "questions",
    ],
    "properties": {
        "decision": {"type": "string", "enum": ["proceed", "needs_human"]},
        "summary": {"type": "string"},
        "implementation_steps": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "acceptance_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion", "evidence"],
                "properties": {
                    "criterion": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "questions": {"type": "array", "items": {"type": "string"}},
    },
}


REVIEW_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "summary", "findings", "questions"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["accept", "repair", "needs_human", "reject"],
        },
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "criterion", "message", "repair"],
                "properties": {
                    "severity": {"type": "string", "enum": ["blocking", "important", "minor"]},
                    "criterion": {"type": "string"},
                    "message": {"type": "string"},
                    "repair": {"type": "string"},
                },
            },
        },
        "questions": {"type": "array", "items": {"type": "string"}},
    },
}

