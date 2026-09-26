from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

import numpy as np
import pandas as pd


CSV_COLUMNS = [
    "name", "area_name", "reference", "uid", "url", "description", "app_type",
    "app_size", "status", "decision", "start_date", "decided_date",
    "days_to_decision", "fetched_at", "n_comments", "n_documents", "n_dwellings",
    "housing_relevance_score", "lat", "lng", "ward_name",
]

UK_BOUNDS = {"min_lat": 49.8, "max_lat": 60.9, "min_lon": -8.7, "max_lon": 1.9}

# Terms that distinguish residential development from generic planning prose.
HOUSING_TERMS = frozenset({
    "apartment", "apartments", "bedroom", "bedrooms", "bungalow", "dwelling",
    "dwellings", "flat", "flats", "home", "homes", "house", "houses", "housing",
    "loft", "residential", "units", "unit", "extension", "extensions", "dormer",
    "redevelopment", "rebuild", "demolition", "new-build", "newbuild",
})


def text_terms(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9-]{2,}", str(text or "").casefold()))


def housing_terms(text: str | None) -> set[str]:
    raw = str(text or "").casefold()
    terms = text_terms(raw) & HOUSING_TERMS
    # A licensed venue is not a residential house merely because its name
    # contains the phrase "public house".
    if "public house" in raw:
        terms.discard("house")
    return terms


def is_housing_related(description: str | None, relevance_score=None) -> bool:
    if housing_terms(description):
        return True
    try:
        return float(relevance_score) >= 0.5
    except (TypeError, ValueError):
        return False


def decision_category(decision: str | None, status: str | None = None) -> str:
    text = f"{decision or ''} {status or ''}".casefold()
    if any(term in text for term in ("refus", "reject", "deny", "denied")):
        return "permission_refused"
    if any(term in text for term in ("withdraw", "invalid", "lapsed", "cancel", "closed")):
        return "withdrawn_or_invalid"
    if any(term in text for term in ("grant", "approv", "permitted", "consent")):
        return "permission_granted"
    if any(term in text for term in ("pending", "undecided", "awaiting")):
        return "pending_or_unknown"
    return "decision_not_recorded"


def validate_coordinates(lat, lon) -> str:
    """Return a reasoned quality state; missing is not treated as outside the UK."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return "missing"
    if not np.isfinite(lat) or not np.isfinite(lon):
        return "missing"
    if not (UK_BOUNDS["min_lat"] <= lat <= UK_BOUNDS["max_lat"] and UK_BOUNDS["min_lon"] <= lon <= UK_BOUNDS["max_lon"]):
        return "out_of_bounds"
    return "valid"


def _available_columns(path: Path) -> list[str]:
    header = pd.read_csv(path, nrows=0)
    return [c for c in CSV_COLUMNS if c in header.columns]


def load_planning_csv(path: str | Path, max_rows: int | None = None) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Planning CSV not found: {path}")
    return pd.read_csv(
        path,
        usecols=_available_columns(path),
        nrows=max_rows,
        low_memory=False,
    )


def _duplicate_counts(df: pd.DataFrame) -> pd.Series:
    key = df.get("uid", pd.Series(index=df.index, dtype="string")).fillna("").astype(str).str.strip()
    key = key.where(key.ne(""), df.get("name", pd.Series(index=df.index, dtype="string")).fillna("").astype(str))
    return key.map(key.value_counts()).astype("Int64")


def prepare_planning_dataframe(df: pd.DataFrame, deduplicate: bool = True) -> pd.DataFrame:
    """Create the stable internal application contract used by retrieval.

    Decision fields are retained for historical evidence only. No approval target is
    trained here, so there is no leakage into the similarity index.
    """
    out = df.copy()
    for col in CSV_COLUMNS:
        if col not in out:
            out[col] = pd.NA

    out["uid"] = out["uid"].fillna("").astype(str).str.strip()
    out["application_id"] = out["uid"].where(out["uid"].ne(""), out["name"].fillna("").astype(str))
    out["authority"] = out["area_name"].fillna("").astype(str).str.strip()
    out["address_text"] = out["name"].fillna("").astype(str).str.strip()
    out["description"] = out["description"].fillna("").astype(str).str.strip()
    out["app_type"] = out["app_type"].fillna("Unknown").astype(str).str.strip()
    out.loc[out["app_type"].eq(""), "app_type"] = "Unknown"
    out["status"] = out["status"].fillna("").astype(str).str.strip()
    out["decision"] = out["decision"].fillna("").astype(str).str.strip()
    out["source_url"] = out["url"].fillna("").astype(str).str.strip()
    out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
    out["lon"] = pd.to_numeric(out["lng"], errors="coerce")
    out["coordinate_quality"] = [validate_coordinates(a, b) for a, b in zip(out["lat"], out["lon"])]
    out["start_date"] = pd.to_datetime(out["start_date"], errors="coerce", utc=True)
    out["decision_date"] = pd.to_datetime(out["decided_date"], errors="coerce", utc=True)
    out["fetched_at"] = pd.to_datetime(out["fetched_at"], errors="coerce", utc=True)
    out["days_to_decision"] = pd.to_numeric(out["days_to_decision"], errors="coerce")
    out["duration_quality"] = np.select(
        [out["days_to_decision"].isna(), out["days_to_decision"].between(0, 3650)],
        ["missing", "valid"],
        default="invalid",
    )
    out["days_to_decision"] = out["days_to_decision"].where(out["duration_quality"].eq("valid"))
    out["n_dwellings"] = pd.to_numeric(out["n_dwellings"], errors="coerce")
    out["n_comments"] = pd.to_numeric(out["n_comments"], errors="coerce")
    out["n_documents"] = pd.to_numeric(out["n_documents"], errors="coerce")
    out["duplicate_count"] = _duplicate_counts(out)

    if deduplicate:
        out = out.sort_values(["fetched_at", "application_id"], na_position="first")
        out = out.drop_duplicates(subset=["application_id"], keep="last")

    keep = [
        "application_id", "uid", "authority", "address_text", "description", "app_type",
        "app_size", "status", "decision", "start_date", "decision_date", "days_to_decision",
        "n_comments", "n_documents", "n_dwellings", "housing_relevance_score", "lat", "lon",
        "ward_name", "source_url", "duplicate_count", "coordinate_quality", "duration_quality",
    ]
    return out[keep].reset_index(drop=True)


def prepare_planning_csv(path: str | Path, output_path: str | Path, max_rows: int | None = None) -> pd.DataFrame:
    raw = load_planning_csv(path, max_rows=max_rows)
    prepared = prepare_planning_dataframe(raw)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prepared.to_parquet(output_path, index=False)
    return prepared


def ensure_prepared(path: str | Path, output_path: str | Path) -> pd.DataFrame:
    output_path = Path(output_path)
    if output_path.exists():
        return pd.read_parquet(output_path)
    return prepare_planning_csv(path, output_path)
