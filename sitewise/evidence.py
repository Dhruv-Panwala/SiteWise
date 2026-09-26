from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings
from .constraints import ConstraintEngine
from .advice import build_planning_advice
from .nearby import NearbyApplicationSearch, outcome_summary
from .planning import validate_coordinates
from .similarity import ComparableCaseIndex


class EvidenceService:
    """Deterministic SiteWise retrieval, before any LLM call."""

    def __init__(
        self,
        applications: pd.DataFrame,
        comparable_index: ComparableCaseIndex,
        settings: Settings | None = None,
        constraints: ConstraintEngine | None = None,
        local_plan_client=None,
    ):
        self.settings = settings or Settings.from_env()
        self.applications = applications
        self.comparable_index = comparable_index
        self.constraints = constraints or ConstraintEngine(self.settings)
        self.nearby = NearbyApplicationSearch(applications)
        self.local_plan_client = local_plan_client
        if self.local_plan_client is None and self.settings.enable_gla_arcgis:
            from .arcgis import GLALocalPlanClient

            self.local_plan_client = GLALocalPlanClient(
                self.settings.cache_dir, base_url=self.settings.arcgis_services_base,
                timeout=self.settings.request_timeout_seconds, cache_ttl=self.settings.cache_ttl_seconds,
            )

    def analyze(
        self,
        lat: float,
        lon: float,
        description: str = "",
        app_type: str | None = None,
        authority: str | None = None,
        radius_m: float = 1000,
        top_n: int = 5,
        exclude_application_id: str | None = None,
    ) -> dict[str, Any]:
        coordinate_quality = validate_coordinates(lat, lon)
        property_record = {
            "latitude": float(lat),
            "longitude": float(lon),
            "coordinate_quality": coordinate_quality,
            "authority": authority,
            "proposed_description": description or None,
            "proposed_application_type": app_type,
        }

        planning_constraints = self.constraints.analyze(lat, lon)
        local_plan = None
        if self.local_plan_client is not None:
            # Let geometry select all overlapping services, including LLDC/OPDC.
            # The planning-CSV authority filter is not a verified boundary lookup.
            local_plan = self.local_plan_client.analyze(lat, lon)
            planning_constraints.extend(local_plan["findings"])
        nearby = self.nearby.find(lat, lon, radius_m=radius_m, limit=max(top_n * 4, 20), authority=authority)
        query = (description or "").strip()
        similar = []
        if query:
            similar = self.comparable_index.search(
                query,
                top_n=top_n,
                lat=lat,
                lon=lon,
                radius_m=max(radius_m * 5, 5000),
                authority=authority,
                app_type=app_type,
                exclude_application_id=exclude_application_id,
                geographical_first=True,
                min_similarity=0.08,
            )

        planning_advice = build_planning_advice(
            planning_constraints, similar, nearby, query=query,
        )

        data_quality = [
            {
                "code": "coordinate_quality",
                "status": coordinate_quality,
                "message": "Coordinates are inside the broad UK bounds." if coordinate_quality == "valid" else "Coordinates are missing or outside UK bounds.",
            },
            {
                "code": "planning_csv",
                "status": "available",
                "message": f"Prepared historical application dataset with {len(self.applications):,} deduplicated records.",
            },
        ]
        for finding in planning_constraints:
            if finding.get("status") in {"unknown", "not_found"}:
                data_quality.append({
                    "code": f"constraint:{finding.get('dataset')}",
                    "status": finding.get("status"),
                    "message": finding.get("coverage_warning"),
                })
        if local_plan is not None:
            data_quality.append({
                "code": "gla_local_plan", "status": local_plan["status"],
                "message": local_plan.get("message") or local_plan["scope"],
            })
            for gap in local_plan["coverage_gaps"]:
                data_quality.append({"code": f"gla:{gap['dataset']}", **gap})
        if not nearby:
            data_quality.append({
                "code": "nearby_applications",
                "status": "not_found",
                "message": f"No prepared applications found within {radius_m:g}m; this is not proof that none exist.",
            })
        if not query:
            data_quality.append({
                "code": "similarity_query",
                "status": "not_available",
                "message": "Add a proposed description to retrieve semantically similar applications.",
            })

        sources = [
            {
                "source_name": "Supplied London planning CSV",
                "source_url": str(self.settings.planning_csv),
                "retrieved_at": None,
                "source_date": None,
            }
        ]
        sources.extend(self.constraints.sources(planning_constraints))
        if local_plan is not None:
            sources.extend({
                "source_name": "GLA Local Plan ArcGIS layer",
                "source_url": layer["source_url"],
                "retrieved_at": layer.get("retrieved_at"), "source_date": None,
            } for layer in local_plan["layers"])
        for row in nearby + similar:
            url = row.get("source_url")
            if url:
                sources.append({"source_name": "Historical planning application", "source_url": url, "retrieved_at": None, "source_date": row.get("decision_date")})
        unique_sources = []
        seen = set()
        for source in sources:
            if source["source_url"] in seen:
                continue
            seen.add(source["source_url"])
            unique_sources.append(source)

        package = {
            "property": property_record,
            "planning_constraints": planning_constraints,
            "nearby_applications": nearby,
            "similar_applications": similar,
            "local_outcome_summary": outcome_summary(nearby),
            "planning_advice": planning_advice,
            "data_quality": data_quality,
            "sources": unique_sources,
        }
        if local_plan is not None:
            package["local_plan"] = local_plan
        return package
