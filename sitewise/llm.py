from __future__ import annotations

import json
import sys
from typing import Any

from .config import Settings


SYSTEM_PROMPT = """You are SiteWise UK, a cautious planning-screening assistant.
Use only the supplied evidence package. Do not determine constraints yourself and do not invent missing planning information.
The user needs a practical screening report for a proposed house/property development.
Start with a short proposal summary. Then use these sections: Comparable permissions, Site constraints, Borough policy evidence, Suggested changes/checks, Data gaps, and Sources.
In Comparable permissions, list only cases in comparable_permissions and identify the application ID, property/address, borough, description, decision, date and source URL. You may separately mention nearby_permissions as local historical evidence. Say clearly when no housing-related permission was retrieved. Never call a weak retrieval match a similar approved home.
In Borough policy evidence, only state a specific rule when policy text or an official policy link is present. Otherwise say that the spatial layer was found but its policy text was not retrieved.
In Suggested changes/checks, use only the deterministic suggestions supplied. A suggestion is a screening action, not a legal conclusion. For trees, explain that the user should plan around the tree and obtain arboricultural/tree-consent advice; do not say a tree is definitely illegal to cut unless the evidence confirms a protection designation.
Every material claim must reference a source URL or application ID from the evidence.
Similarity scores are retrieval scores, not approval probabilities. Historical outcomes are not guarantees.
State uncertainty explicitly and state that this is screening information, not legal, planning, ecological or investment advice."""


def _short(value: Any, limit: int) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _select(item: dict[str, Any], keys: tuple[str, ...], text_limit: int) -> dict[str, Any]:
    return {
        key: _short(item.get(key), text_limit)
        for key in keys
        if item.get(key) is not None
    }


def build_llm_evidence(
    evidence: dict[str, Any],
    *,
    max_nearby_cases: int = 6,
    max_similar_cases: int = 5,
    description_limit: int = 500,
    max_input_chars: int = 24_000,
) -> dict[str, Any]:
    """Create a small, deterministic report payload without altering full evidence.

    Nearby and similar applications arrive in relevance order, so taking the head
    preserves geographic and semantic ranking. Fields used only by the dashboard
    (such as duplicate coordinates) are omitted from the LLM context.
    """
    nearby_all = evidence.get("nearby_applications") or []
    similar_all = evidence.get("similar_applications") or []
    constraint_all = evidence.get("planning_constraints") or []

    case_keys = (
        "application_id", "authority", "address_text", "description", "app_type",
        "decision", "decision_date", "days_to_decision", "distance_m",
        "similarity_score", "source_url", "constraint_information",
    )
    constraint_keys = (
        "constraint_id", "dataset", "name", "severity", "status", "current",
        "raw_reference", "coverage_warning", "spatial_relation", "source_url",
        "source_name", "source_date",
    )
    property_keys = (
        "latitude", "longitude", "coordinate_quality", "authority",
        "proposed_description", "proposed_application_type",
    )

    compact: dict[str, Any] = {
        "property": _select(evidence.get("property") or {}, property_keys, description_limit),
        "planning_constraints": [
            _select(item, constraint_keys, description_limit) for item in constraint_all
        ],
        "nearby_applications": [
            _select(item, case_keys, description_limit)
            for item in nearby_all[:max(0, max_nearby_cases)]
        ],
        "similar_applications": [
            _select(item, case_keys, description_limit)
            for item in similar_all[:max(0, max_similar_cases)]
        ],
        "local_outcome_summary": evidence.get("local_outcome_summary") or {},
        "planning_advice": evidence.get("planning_advice") or {},
        "data_quality": [
            _select(item, ("code", "status", "message"), description_limit)
            for item in (evidence.get("data_quality") or [])
        ],
        "selection_note": {
            "nearby_available": len(nearby_all),
            "nearby_included": min(len(nearby_all), max(0, max_nearby_cases)),
            "similar_available": len(similar_all),
            "similar_included": min(len(similar_all), max(0, max_similar_cases)),
            "policy": "Nearest nearby cases and highest-ranked comparable cases only; full evidence remains outside the LLM prompt.",
        },
    }

    # Maintain valid JSON while enforcing a hard context-size ceiling. Less useful
    # tail cases are removed first; constraints and data-quality warnings remain.
    def payload_size() -> int:
        return len(json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str))

    while payload_size() > max_input_chars:
        nearby = compact["nearby_applications"]
        similar = compact["similar_applications"]
        if len(nearby) >= len(similar) and nearby:
            nearby.pop()
        elif similar:
            similar.pop()
        else:
            break
    compact["selection_note"]["nearby_included"] = len(compact["nearby_applications"])
    compact["selection_note"]["similar_included"] = len(compact["similar_applications"])
    return compact


def build_prompt(
    evidence: dict[str, Any],
    settings: Settings,
    *,
    compatibility_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    max_nearby = min(settings.hf_max_nearby_cases, 3) if compatibility_mode else settings.hf_max_nearby_cases
    max_similar = min(settings.hf_max_similar_cases, 3) if compatibility_mode else settings.hf_max_similar_cases
    description_limit = min(settings.hf_max_description_chars, 300) if compatibility_mode else settings.hf_max_description_chars
    max_input_chars = min(settings.hf_max_input_chars, 10_000) if compatibility_mode else settings.hf_max_input_chars
    compact = build_llm_evidence(
        evidence,
        max_nearby_cases=max_nearby,
        max_similar_cases=max_similar,
        description_limit=description_limit,
        max_input_chars=max_input_chars,
    )
    prompt = "Prepare a plain-English screening report from this curated deterministic evidence:\n\n" + json.dumps(
        compact, ensure_ascii=False, separators=(",", ":"), default=str
    )
    return prompt, compact["selection_note"]


def build_ultra_prompt(evidence: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Smallest provider-compatible report input after larger chat requests fail."""
    advice = evidence.get("planning_advice") or {}
    case_keys = (
        "application_id", "authority", "address_text", "description", "decision",
        "decision_date", "similarity_match_quality", "source_url",
    )
    suggestion_keys = ("priority", "title", "action", "basis", "source_urls")
    policy_keys = ("authority", "designation", "policy_status", "policy_references", "source_urls", "message")
    gap_keys = ("name", "dataset", "status", "message", "source_url")
    payload = {
        "proposal": _select(evidence.get("property") or {}, ("authority", "proposed_description", "proposed_application_type"), 280),
        "comparable_permissions": [_select(x, case_keys, 220) for x in (advice.get("comparable_permissions") or [])[:2]],
        "comparable_refusals": [_select(x, case_keys, 180) for x in (advice.get("comparable_refusals") or [])[:2]],
        "suggested_checks": [_select(x, suggestion_keys, 220) for x in (advice.get("suggestions") or [])[:5]],
        "borough_policy_evidence": [_select(x, policy_keys, 180) for x in (advice.get("borough_policy_evidence") or [])[:3]],
        "data_gaps": [_select(x, gap_keys, 180) for x in (advice.get("data_gaps") or [])[:4]],
    }
    summary = {
        "mode": "ultra_compact",
        "comparable_permissions_included": len(payload["comparable_permissions"]),
        "comparable_refusals_included": len(payload["comparable_refusals"]),
        "suggestions_included": len(payload["suggested_checks"]),
        "policy_items_included": len(payload["borough_policy_evidence"]),
        "data_gaps_included": len(payload["data_gaps"]),
    }
    return "Write the requested concise planning screen from this verified evidence only:\n" + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), default=str
    ), summary


def build_messages(prompt: str, provider: str) -> list[dict[str, str]]:
    # Featherless successfully serves Phi-4 Mini with a single user message but
    # can reject the separate system-role request with a generic 400 response.
    if provider.strip().lower() == "featherless-ai":
        return [{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{prompt}"}]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def build_ultra_messages(prompt: str) -> list[dict[str, str]]:
    """Mirror the smallest successful Phi/Featherless smoke-test shape."""
    return [{"role": "user", "content": prompt}]


def print_llm_context(
    attempt: str,
    *,
    model: str,
    provider: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> None:
    """Print the exact non-secret request context to stderr for debugging."""
    print(f"\n--- SiteWise LLM input: {attempt} ---", file=sys.stderr)
    print(json.dumps({
        "model": model,
        "provider": provider,
        "max_tokens": max_tokens,
        "messages": messages,
    }, ensure_ascii=False, indent=2), file=sys.stderr)
    print(f"--- End SiteWise LLM input: {attempt} ---\n", file=sys.stderr)


def _safe_error(exc: Exception, token: str | None) -> str:
    detail = str(exc).strip().replace("\r", " ").replace("\n", " ")
    if token:
        detail = detail.replace(token, "[REDACTED]")
    detail = " ".join(detail.split())
    return _short(detail, 600) or "No provider error detail was returned."


def generate_report(
    evidence: dict[str, Any],
    settings: Settings | None = None,
    *,
    debug_print_context: bool = False,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    if not settings.hf_token:
        return {
            "status": "not_configured",
            "model": settings.hf_model,
            "text": None,
            "message": "HF_TOKEN is not configured; deterministic evidence is still available.",
        }
    prompt = ""
    selection_note: dict[str, Any] = {}
    attempts: list[str] = []
    try:
        from huggingface_hub import InferenceClient

        prompt, selection_note = build_prompt(evidence, settings)
        client = InferenceClient(provider=settings.hf_provider, api_key=settings.hf_token)
        request_args = {
            "model": settings.hf_model,
            "messages": build_messages(prompt, settings.hf_provider),
            "max_tokens": settings.hf_max_new_tokens,
            "temperature": settings.hf_temperature,
        }
        compatibility_retry = False
        try:
            attempts.append("standard")
            if debug_print_context:
                print_llm_context(
                    "standard", model=settings.hf_model, provider=settings.hf_provider,
                    messages=request_args["messages"], max_tokens=request_args["max_tokens"],
                )
            response = client.chat.completions.create(**request_args)
        except Exception as first_exc:
            if first_exc.__class__.__name__ != "BadRequestError":
                raise
            compatibility_retry = True
            prompt, selection_note = build_prompt(evidence, settings, compatibility_mode=True)
            try:
                attempts.append("compact")
                compact_args = {
                    "model": settings.hf_model,
                    "provider": settings.hf_provider,
                    "messages": build_messages(prompt, settings.hf_provider),
                    "max_tokens": min(settings.hf_max_new_tokens, 400),
                }
                if debug_print_context:
                    print_llm_context("compact", **compact_args)
                response = client.chat.completions.create(
                    model=compact_args["model"], messages=compact_args["messages"], max_tokens=compact_args["max_tokens"],
                )
            except Exception as compact_exc:
                if compact_exc.__class__.__name__ != "BadRequestError":
                    raise
                prompt, selection_note = build_ultra_prompt(evidence)
                attempts.append("ultra_compact")
                ultra_args = {
                    "model": settings.hf_model,
                    "provider": settings.hf_provider,
                    "messages": build_ultra_messages(prompt),
                    "max_tokens": 160,
                }
                if debug_print_context:
                    print_llm_context("ultra_compact", **ultra_args)
                response = client.chat.completions.create(
                    model=ultra_args["model"], messages=ultra_args["messages"], max_tokens=ultra_args["max_tokens"],
                )
        text = response.choices[0].message.content if response.choices else ""
        return {
            "status": "generated",
            "model": settings.hf_model,
            "provider": settings.hf_provider,
            "text": text,
            "input_summary": {
                **selection_note,
                "prompt_characters": len(prompt),
                "compatibility_retry": compatibility_retry,
                "attempts": attempts,
            },
        }
    except Exception as exc:  # provider availability is optional for the MVP
        result = {
            "status": "unavailable",
            "model": settings.hf_model,
            "provider": settings.hf_provider,
            "text": None,
            "message": f"Hugging Face report generation failed ({exc.__class__.__name__}): {_safe_error(exc, settings.hf_token)}",
        }
        if prompt:
            result["input_summary"] = {**selection_note, "prompt_characters": len(prompt), "attempts": attempts}
        return result
