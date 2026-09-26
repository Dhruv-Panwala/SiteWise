"""Deterministic planning advice assembled from retrieved evidence only."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .planning import decision_category, is_housing_related


def _source_urls(item: dict[str, Any]) -> list[str]:
    urls = [item.get("source_url"), item.get("layer_url")]
    urls.extend(item.get("policy_links") or [])
    return list(dict.fromkeys(str(url) for url in urls if url))


def _case(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
        "application_id", "authority", "address_text", "description", "app_type",
            "status", "decision", "decision_category", "decision_date", "distance_m",
            "similarity_score", "similarity_match_quality", "source_url",
        )
        if item.get(key) is not None
    }


def _constraint_advice(finding: dict[str, Any]) -> dict[str, Any] | None:
    dataset = str(finding.get("dataset") or "")
    status = finding.get("status")
    if status not in {"confirmed", "historical"}:
        return None
    source_urls = _source_urls(finding)
    if dataset == "conservation-area":
        title = "Conservation-area design review"
        action = "Check the borough conservation-area appraisal and prepare a heritage/design explanation for scale, materials, views and local character."
    elif dataset == "tree-preservation-zone":
        title = "Protected-tree check"
        action = "Do not assume the tree can be removed. Commission an arboricultural survey, show retention and root-protection measures, and check whether separate tree consent is required."
    elif dataset == "flood-risk-zone":
        title = "Flood-risk evidence"
        action = "Obtain the appropriate flood-risk assessment and explain drainage, surface-water and SuDS measures before fixing the site layout."
    elif dataset == "green-belt":
        title = "Green Belt policy check"
        action = "Check the borough Green Belt policy, openness and development exceptions; the retrieved layer is a policy flag, not a permission decision."
    elif dataset == "listed-building":
        title = "Listed-building heritage check"
        action = "Check listed-building status and whether listed-building consent or a heritage impact assessment is needed in addition to planning permission."
    elif dataset == "article-4-direction-area":
        title = "Article 4 permitted-development check"
        action = "Check the specific Article 4 direction because permitted-development rights may be restricted and a full application may be required."
    elif dataset == "ancient-woodland":
        title = "Ancient-woodland buffer check"
        action = "Keep the layout away from the woodland and confirm the relevant buffer, ecology evidence and mitigation with the planning authority."
    elif dataset == "site-of-special-scientific-interest":
        title = "Protected-nature-site check"
        action = "Obtain ecology advice and check whether the proposal could affect the designated site, including indirect effects."
    elif dataset.startswith("local-plan:"):
        title = f"Local-plan layer: {finding.get('layer_name') or finding.get('name') or dataset.removeprefix('local-plan:')}"
        action = "Read the linked borough/local-plan policy before fixing the scheme's use, height, massing, access and housing mix."
    else:
        return None
    if status == "historical":
        action = "Historical designation only; verify whether it still applies before acting. If it does: " + action
    return {
        "dataset": dataset,
        "priority": "high" if dataset in {"tree-preservation-zone", "listed-building", "ancient-woodland", "site-of-special-scientific-interest"} else "medium",
        "title": title, "action": action, "basis": "point_intersection",
        "constraint": finding.get("name") or dataset, "status": status,
        "source_urls": source_urls,
        "source_date": finding.get("source_date"),
    }


def _policy_evidence(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output, seen = [], set()
    for finding in findings:
        if not str(finding.get("dataset") or "").startswith("local-plan:") and finding.get("source_name") != "GLA Local Plan ArcGIS":
            continue
        key = (finding.get("dataset"), finding.get("name"), finding.get("layer_name"))
        if key in seen:
            continue
        seen.add(key)
        links = _source_urls(finding)
        details = finding.get("source_details") or {}
        policy_references = [str(value) for key, value in details.items() if key.startswith("extrainfo") and value]
        if finding.get("policy_links"):
            policy_status = "policy_source_linked"
            message = "An official policy/source link was returned; read it before treating this layer as a borough rule."
        elif policy_references:
            policy_status = "policy_reference_found"
            message = "The layer contains a policy reference, but the policy text or direct URL was not retrieved."
        else:
            policy_status = "policy_text_not_retrieved"
            message = "The spatial layer was returned but its policy text was not retrieved; no specific borough rule is asserted."
        output.append({
            "authority": finding.get("authority") or finding.get("borough"),
            "designation": finding.get("name") or finding.get("dataset"),
            "layer_name": finding.get("layer_name"),
            "policy_status": policy_status,
            "source_urls": links,
            "policy_references": policy_references,
            "message": message,
        })
    return output


def build_planning_advice(
    constraints: Iterable[dict[str, Any]],
    similar: list[dict[str, Any]],
    nearby: list[dict[str, Any]],
    *,
    query: str = "",
) -> dict[str, Any]:
    constraints = list(constraints)
    def usable_comparable(item: dict[str, Any]) -> bool:
        return item.get("similarity_match_quality") in {None, "strong", "moderate"}
    all_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in similar + nearby:
        identity = str(item.get("application_id") or item.get("source_url") or id(item))
        if identity in seen_ids:
            continue
        seen_ids.add(identity)
        all_cases.append(item)
    comparable_permissions = [
        _case(x) for x in similar
        if x.get("decision_category") == "permission_granted" and x.get("housing_related") and usable_comparable(x)
    ]
    comparable_refusals = [
        _case(x) for x in similar
        if x.get("decision_category") == "permission_refused" and x.get("housing_related") and usable_comparable(x)
    ]
    nearby_permissions = [
        _case(x) for x in nearby
        if x.get("decision_category") == "permission_granted" and x.get("housing_related")
    ]
    decision_counts = Counter(x.get("decision_category") for x in all_cases if x.get("decision_category"))
    suggestions = [x for finding in constraints if (x := _constraint_advice(finding))]
    local_suggestions = [x for x in suggestions if str(x.get("dataset") or "").startswith("local-plan:")]
    if len(local_suggestions) > 4:
        suggestions = [x for x in suggestions if not str(x.get("dataset") or "").startswith("local-plan:")]
        local_names = list(dict.fromkeys(str(x.get("constraint")) for x in local_suggestions if x.get("constraint")))
        local_urls = list(dict.fromkeys(url for x in local_suggestions for url in x.get("source_urls", []) if url))
        suggestions.append({
            "priority": "medium", "title": "Review the applicable borough/local-plan designations",
            "action": "The point intersects several published local-plan designations: " + ", ".join(local_names[:8]) + (" and others." if len(local_names) > 8 else ".") + " Read the policy references and confirm how they affect height, massing, use, access and housing mix before finalising the scheme.",
            "basis": "point_intersection", "source_urls": local_urls,
        })
    gap_statuses = {"unknown", "not_found", "not_available"}
    gaps = []
    gap_seen = set()
    intersected = {x.get("dataset") for x in constraints if x.get("status") == "confirmed"}
    for finding in constraints:
        dataset = str(finding.get("dataset") or "")
        if finding.get("status") not in gap_statuses or dataset in gap_seen or dataset in intersected:
            continue
        gap_seen.add(dataset)
        gaps.append({
            "dataset": dataset,
            "name": finding.get("name") or dataset,
            "status": finding.get("status"),
            "source_url": finding.get("source_url"),
            "message": "Not verified for this site. Check the council register before finalising the design."
                       if "disabled" in str(finding.get("coverage_warning", "")).lower()
                       else finding.get("coverage_warning") or "This source did not confirm or rule out the constraint.",
        })
    if gaps:
        suggestions.append({
            "priority": "high", "title": "Verify unconfirmed constraints before fixing the design",
            "action": "The available point sources did not confirm or rule out every listed constraint. Check the borough register and current official policy for the unconfirmed categories before treating the site as clear.",
            "basis": "data_gap", "source_urls": [x["source_url"] for x in gaps if x.get("source_url")],
        })
        gap_names = {x["dataset"] for x in gaps}
        if "tree-preservation-zone" in gap_names:
            suggestions.append({
                "priority": "high", "title": "Verify tree protection before fixing the layout",
                "action": "Tree protection was not confirmed by the available point source. Check the borough TPO/tree register and obtain an arboricultural view before assuming any tree can be removed or designing through its root-protection area.",
                "basis": "data_gap", "source_urls": [x["source_url"] for x in gaps if x["dataset"] == "tree-preservation-zone" and x.get("source_url")],
            })
    if comparable_permissions:
        suggestions.append({
            "priority": "medium", "title": "Use permitted cases as design evidence",
            "action": "Compare the permitted homes by scale, housing type, authority and site constraints; cite the application IDs rather than treating permission as a guarantee.",
            "basis": "historical_comparable_cases", "source_urls": [x["source_url"] for x in comparable_permissions if x.get("source_url")],
        })
    if comparable_refusals:
        suggestions.append({
            "priority": "high", "title": "Review refused housing cases",
            "action": "Retrieve the decision notices and officer reasons for the refused cases; the supplied planning CSV records outcomes but not the reasons for refusal.",
            "basis": "historical_comparable_cases", "source_urls": [x["source_url"] for x in comparable_refusals if x.get("source_url")],
        })
    if not comparable_permissions:
        suggestions.append({
            "priority": "high", "title": "No verified comparable permission found",
            "action": "The retrieved cases do not contain a housing-related permission that is sufficiently comparable. Do not rely on the weak matches; inspect the borough register for closer applications and decision notices.",
            "basis": "data_gap", "source_urls": [],
        })
    return {
        "comparable_permissions": comparable_permissions,
        "comparable_refusals": comparable_refusals,
        "nearby_permissions": nearby_permissions,
        "decision_counts": dict(decision_counts),
        "data_gaps": gaps,
        "suggestions": suggestions,
        "borough_policy_evidence": _policy_evidence(constraints),
        "limitations": [
            "The supplied CSV gives application descriptions and outcomes, but not officer reasons, drawings, conditions or complete policy text.",
            "A point intersection is not a full site-boundary or tree-canopy assessment.",
            "Historical permission is evidence for comparison, not a guarantee for this proposal.",
        ],
    }
