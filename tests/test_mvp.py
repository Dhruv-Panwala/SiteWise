from __future__ import annotations

import json

import pandas as pd

from sitewise.config import Settings
from sitewise.constraints import ConstraintEngine, GeoJSONConstraintIndex
from sitewise.advice import build_planning_advice
from sitewise.evidence import EvidenceService
from sitewise.llm import SYSTEM_PROMPT, build_llm_evidence, build_messages, build_ultra_messages, build_ultra_prompt, print_llm_context
from sitewise.nearby import NearbyApplicationSearch
from sitewise.planning import prepare_planning_dataframe, validate_coordinates
from sitewise.planning import is_housing_related
from sitewise.similarity import ComparableCaseIndex


def sample_applications() -> pd.DataFrame:
    raw = pd.DataFrame([
        {"name": "1 High Street", "area_name": "Test Borough", "uid": "a", "url": "https://example/a", "description": "Construction of a rear dormer and roof lights", "app_type": "Full", "status": "Permitted", "decision": "Approved", "start_date": "2023-01-01", "decided_date": "2023-02-01", "days_to_decision": 31, "lat": 51.50, "lng": -0.10, "fetched_at": "2024-01-01"},
        {"name": "2 High Street", "area_name": "Test Borough", "uid": "b", "url": "https://example/b", "description": "Two storey rear extension and loft conversion", "app_type": "Full", "status": "Rejected", "decision": "Refused", "start_date": "2023-01-01", "decided_date": "2023-03-01", "days_to_decision": 59, "lat": 51.501, "lng": -0.101, "fetched_at": "2024-01-01"},
        {"name": "3 High Street", "area_name": "Other Borough", "uid": "c", "url": "https://example/c", "description": "New detached dwelling", "app_type": "Outline", "status": "Permitted", "decision": "Approved", "start_date": "2023-01-01", "decided_date": "2023-04-01", "days_to_decision": 90, "lat": 51.60, "lng": -0.20, "fetched_at": "2024-01-01"},
    ])
    return prepare_planning_dataframe(raw)


def test_coordinate_quality():
    assert validate_coordinates(51.5, -0.1) == "valid"
    assert validate_coordinates(None, -0.1) == "missing"
    assert validate_coordinates(0, 0) == "out_of_bounds"


def test_similarity_returns_evidence_not_probability(tmp_path):
    apps = sample_applications()
    index = ComparableCaseIndex.build(apps, tmp_path / "index")
    results = index.search("rear dormer roof lights", top_n=1, lat=51.5, lon=-0.1)
    assert results[0]["application_id"] == "a"
    assert 0 < results[0]["similarity_score"] <= 1
    assert "approval_probability" not in results[0]
    assert results[0]["source_url"] == "https://example/a"
    assert results[0]["decision_category"] == "permission_granted"
    assert results[0]["housing_related"] is True


def test_nearby_returns_distance_and_constraint_unknown_state():
    apps = sample_applications()
    results = NearbyApplicationSearch(apps).find(51.5, -0.1, radius_m=500, limit=10)
    assert results
    assert results[0]["distance_m"] < 200
    assert results[0]["constraint_information"]["status"] == "not_available"


def test_local_constraint_index_uses_point_intersection(tmp_path):
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "Example TPO", "reference": "TPO-1"},
            "geometry": {"type": "Polygon", "coordinates": [[[-0.11, 51.49], [-0.09, 51.49], [-0.09, 51.51], [-0.11, 51.51], [-0.11, 51.49]]]},
        }],
    }
    path = tmp_path / "tree-preservation-zone.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")
    findings = GeoJSONConstraintIndex.from_directory(tmp_path).query(51.5, -0.1)
    assert findings[0]["status"] == "confirmed"
    assert findings[0]["raw_reference"] == "TPO-1"


def test_constraint_engine_surfaces_unknown_when_live_api_disabled(tmp_path):
    settings = Settings.from_env(root=tmp_path, load_env_file=False)
    findings = ConstraintEngine(settings=settings, local_index=GeoJSONConstraintIndex([])).analyze(51.5, -0.1)
    assert findings
    assert all(item["status"] == "unknown" for item in findings)


def test_evidence_package_is_structured_before_llm(tmp_path):
    apps = sample_applications()
    index = ComparableCaseIndex.build(apps, tmp_path / "index")
    settings = Settings.from_env(root=tmp_path, load_env_file=False)
    package = EvidenceService(apps, index, settings=settings, constraints=ConstraintEngine(settings=settings, local_index=GeoJSONConstraintIndex([]))).analyze(
        51.5, -0.1, description="rear dormer and roof lights", radius_m=500, top_n=2
    )
    assert set(package) == {"property", "planning_constraints", "nearby_applications", "similar_applications", "local_outcome_summary", "planning_advice", "data_quality", "sources"}
    assert package["similar_applications"]
    assert package["planning_advice"]["suggestions"]


def test_llm_evidence_is_compact_and_relevance_limited():
    long_text = "rear extension " * 200
    case = {
        "application_id": "case-1",
        "description": long_text,
        "decision": "Approved",
        "distance_m": 10,
        "lat": 51.5,
        "lon": -0.1,
        "source_url": "https://example/case-1",
    }
    evidence = {
        "property": {"latitude": 51.5, "longitude": -0.1, "proposed_description": long_text},
        "planning_constraints": [],
        "nearby_applications": [dict(case, application_id=f"near-{i}") for i in range(20)],
        "similar_applications": [dict(case, application_id=f"similar-{i}") for i in range(20)],
        "local_outcome_summary": {"application_count": 20},
        "data_quality": [],
        "sources": [{"source_url": f"https://example/{i}"} for i in range(100)],
    }
    compact = build_llm_evidence(
        evidence,
        max_nearby_cases=3,
        max_similar_cases=2,
        description_limit=100,
        max_input_chars=5_000,
    )
    assert len(compact["nearby_applications"]) == 3
    assert len(compact["similar_applications"]) == 2
    assert len(compact["nearby_applications"][0]["description"]) == 100
    assert "lat" not in compact["nearby_applications"][0]
    assert "sources" not in compact
    assert compact["selection_note"]["nearby_available"] == 20
    assert len(json.dumps(compact, ensure_ascii=False, separators=(",", ":"))) <= 5_000
    assert len(evidence["nearby_applications"]) == 20


def test_ultra_prompt_only_contains_report_decision_evidence():
    evidence = {
        "property": {"proposed_description": "Rear extension to house", "latitude": 51.5},
        "nearby_applications": [{"description": "This should not be sent"}],
        "planning_constraints": [{"name": "This should not be sent"}],
        "planning_advice": {
            "comparable_permissions": [{"application_id": "a", "description": "Permitted dwelling", "source_url": "https://example/a"}],
            "comparable_refusals": [{"application_id": "b", "description": "Refused dwelling", "source_url": "https://example/b"}],
            "suggestions": [{"title": "Check tree", "action": "Get arboricultural advice"}],
            "borough_policy_evidence": [{"designation": "Conservation Area", "policy_status": "policy_text_not_retrieved"}],
            "data_gaps": [{"dataset": "tree-preservation-zone", "status": "unknown"}],
        },
    }
    prompt, summary = build_ultra_prompt(evidence)
    assert "Permitted dwelling" in prompt
    assert "This should not be sent" not in prompt
    assert summary["mode"] == "ultra_compact"
    assert summary["comparable_permissions_included"] == 1


def test_featherless_uses_provider_compatible_single_message():
    messages = build_messages("evidence", "featherless-ai")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert SYSTEM_PROMPT in messages[0]["content"]


def test_other_providers_keep_system_message():
    messages = build_messages("evidence", "auto")
    assert [message["role"] for message in messages] == ["system", "user"]


def test_ultra_messages_preserve_grounding_on_every_retry():
    messages = build_ultra_messages("evidence")
    assert messages[0]["role"] == "user"
    assert SYSTEM_PROMPT in messages[0]["content"]
    assert messages[0]["content"].endswith("evidence")


def test_print_llm_context_excludes_credentials(capsys):
    print_llm_context("test", model="microsoft/Phi-4-mini-instruct", provider="featherless-ai", messages=[{"role": "user", "content": "safe evidence"}], max_tokens=160)
    captured = capsys.readouterr()
    assert "safe evidence" in captured.err
    assert "HF_TOKEN" not in captured.err


def test_planning_advice_separates_permissions_policy_references_and_gaps():
    similar = [{
        "application_id": "grant-1", "authority": "Test Borough", "address_text": "1 High Street",
        "description": "Two storey rear extension to dwelling", "decision": "Granted Permission",
        "decision_category": "permission_granted", "housing_related": True,
        "similarity_score": 0.31, "source_url": "https://example/grant-1",
    }, {
        "application_id": "bar-1", "authority": "Test Borough", "address_text": "2 High Street",
        "description": "Change of use of plant room to bar", "decision": "Granted Permission",
        "decision_category": "permission_granted", "housing_related": False,
        "similarity_score": 0.12, "source_url": "https://example/bar-1",
    }]
    constraints = [{
        "dataset": "tree-preservation-zone", "name": "Protected tree zone", "status": "unknown",
        "coverage_warning": "Tree layer unavailable", "source_url": "https://example/tree",
    }, {
        "dataset": "conservation-area", "name": "Test conservation area", "status": "confirmed",
        "source_url": "https://example/record", "source_details": {"extrainfo1": "Policy 3 - Character"},
        "layer_name": "Conservation Areas", "source_name": "GLA Local Plan ArcGIS",
    }]
    advice = build_planning_advice(constraints, similar, [], query="rear extension home")
    assert [x["application_id"] for x in advice["comparable_permissions"]] == ["grant-1"]
    assert advice["data_gaps"][0]["dataset"] == "tree-preservation-zone"
    assert advice["borough_policy_evidence"][0]["policy_status"] == "policy_reference_found"
    assert any(x["title"] == "Verify tree protection before fixing the layout" for x in advice["suggestions"])
    assert is_housing_related("Change of use of a public house to a restaurant") is False


def test_gla_findings_provenance_and_gaps_flow_into_evidence(tmp_path):
    class LocalPlan:
        def analyze(self, lat, lon):
            return {
                "status": "partial", "scope": "Published GLA layers",
                "findings": [{"dataset": "conservation-area", "status": "confirmed",
                              "name": "Test conservation area", "source_url": "https://example/gla/record",
                              "source_name": "GLA", "current": None}],
                "layers": [{"source_url": "https://example/gla/layer"}],
                "coverage_gaps": [{"dataset": "tree-preservation-zone", "status": "not_available",
                                   "message": "No tree layer in this service"}],
            }
    apps = sample_applications()
    settings = Settings.from_env(root=tmp_path, load_env_file=False)
    index = ComparableCaseIndex.build(apps, tmp_path / "index")
    package = EvidenceService(apps, index, settings=settings,
                              constraints=ConstraintEngine(settings=settings, local_index=GeoJSONConstraintIndex([])),
                              local_plan_client=LocalPlan()).analyze(51.5, -0.1)
    assert package["local_plan"]["status"] == "partial"
    assert any(c.get("name") == "Test conservation area" for c in package["planning_constraints"])
    assert any(s["source_url"] == "https://example/gla/record" for s in package["sources"])
    assert any(q["code"] == "gla:tree-preservation-zone" for q in package["data_quality"])
    assert "llm_report" not in package
