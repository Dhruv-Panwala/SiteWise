from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .spatial import haversine_m
from .planning import decision_category, is_housing_related


def _value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


class NearbyApplicationSearch:
    def __init__(self, applications: pd.DataFrame):
        self.applications = applications.reset_index(drop=True)

    def find(
        self,
        lat: float,
        lon: float,
        radius_m: float = 1000,
        limit: int = 20,
        authority: str | None = None,
        app_type: str | None = None,
    ) -> list[dict]:
        df = self.applications
        valid = df.get("coordinate_quality", pd.Series(index=df.index, dtype=object)).eq("valid")
        if authority:
            valid &= df["authority"].eq(authority)
        if app_type:
            valid &= df["app_type"].eq(app_type)
        if not valid.any():
            return []
        subset = df.loc[valid].copy()
        subset["distance_m"] = haversine_m(subset["lat"], subset["lon"], lat, lon)
        subset = subset[subset["distance_m"] <= float(radius_m)].sort_values("distance_m").head(limit)
        results = []
        for _, row in subset.iterrows():
            result = {
                "application_id": _value(row.get("application_id")),
                "authority": _value(row.get("authority")),
                "address_text": _value(row.get("address_text")),
                "description": _value(row.get("description")),
                "app_type": _value(row.get("app_type")),
                "decision": _value(row.get("decision")),
                "decision_date": _value(row.get("decision_date")),
                "days_to_decision": _value(row.get("days_to_decision")),
                "lat": _value(row.get("lat")),
                "lon": _value(row.get("lon")),
                "source_url": _value(row.get("source_url")),
                "distance_m": round(float(row["distance_m"]), 1),
                "decision_category": decision_category(row.get("decision"), row.get("status")),
                "housing_related": is_housing_related(row.get("description"), row.get("housing_relevance_score")),
            }
            # The supplied CSV has no historical constraint columns. Keep that
            # limitation explicit rather than inferring constraints from text.
            result["constraint_information"] = {
                "status": "available" if "constraint_summary" in row and pd.notna(row.get("constraint_summary")) else "not_available",
                "value": _value(row.get("constraint_summary")) if "constraint_summary" in row else None,
                "reason": "No historical constraint fields are present in the supplied CSV." if "constraint_summary" not in row else None,
            }
            results.append(result)
        return results


def outcome_summary(applications: list[dict]) -> dict:
    """Descriptive retrospective summary, never an approval prediction."""
    decisions = [str(row.get("decision") or "").strip() for row in applications]
    decisions = [d for d in decisions if d]
    counts = pd.Series(decisions).value_counts().to_dict() if decisions else {}
    days = [row.get("days_to_decision") for row in applications if row.get("days_to_decision") is not None]
    return {
        "application_count": len(applications),
        "decision_breakdown": {str(k): int(v) for k, v in counts.items()},
        "median_decision_days": float(np.median(days)) if days else None,
        "basis": "Historical nearby records only; not a probability of approval.",
    }
