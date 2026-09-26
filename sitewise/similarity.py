from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

from .spatial import haversine_m
from .planning import decision_category, housing_terms, is_housing_related


DEFAULT_MAX_FEATURES = 15_000


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


class ComparableCaseIndex:
    """TF-IDF comparable-case index adapted from the spike's browser model.

    This index ranks historical applications by text similarity. It deliberately
    exposes no approval probability and keeps decision fields as retrospective
    evidence only.
    """

    def __init__(self, metadata: pd.DataFrame, vectorizer: TfidfVectorizer, matrix: sparse.csr_matrix):
        self.metadata = metadata.reset_index(drop=True)
        self.vectorizer = vectorizer
        self.matrix = matrix.tocsr()

    @classmethod
    def build(
        cls,
        applications: pd.DataFrame,
        output_dir: str | Path | None = None,
        max_features: int = DEFAULT_MAX_FEATURES,
        max_cases: int | None = None,
    ) -> "ComparableCaseIndex":
        cols = [
            "application_id", "authority", "address_text", "description", "app_type",
            "status", "decision", "decision_date", "days_to_decision", "lat", "lon", "source_url",
        ]
        missing = [c for c in cols if c not in applications.columns]
        if missing:
            raise ValueError(f"Prepared applications missing columns: {missing}")
        work = applications.loc[applications["description"].fillna("").str.len().ge(10)].copy()
        work = work.loc[work["coordinate_quality"].eq("valid")] if "coordinate_quality" in work else work
        work = work.sort_values(["decision_date", "application_id"], na_position="last")
        if max_cases and len(work) > max_cases:
            # Keep a deterministic, time-balanced corpus rather than an arbitrary head.
            positions = np.linspace(0, len(work) - 1, max_cases, dtype=int)
            work = work.iloc[np.unique(positions)]
        text = work["description"].fillna("").astype(str).str.lower().str.strip()
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=2,
            max_features=max_features,
            sublinear_tf=True,
            lowercase=True,
            token_pattern=r"(?u)\b\w\w+\b",
            dtype=np.float32,
        )
        matrix = vectorizer.fit_transform(text).tocsr()
        metadata = work[cols].copy().reset_index(drop=True)
        metadata["decision_date"] = pd.to_datetime(metadata["decision_date"], errors="coerce", utc=True)
        index = cls(metadata, vectorizer, matrix)
        if output_dir:
            index.save(output_dir)
        return index

    def save(self, output_dir: str | Path) -> None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.metadata.to_parquet(output_dir / "comparable_cases.parquet", index=False)
        sparse.save_npz(output_dir / "comparable_tfidf.npz", self.matrix, compressed=True)
        joblib.dump(self.vectorizer, output_dir / "comparable_vectorizer.joblib", compress=3)
        manifest = {
            "rows": len(self.metadata),
            "features": int(self.matrix.shape[1]),
            "ngram_range": [1, 2],
            "max_features": int(self.matrix.shape[1]),
            "similarity": "cosine similarity over L2-normalised TF-IDF word unigrams/bigrams",
            "decision_is_evidence_only": True,
        }
        (output_dir / "comparable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, output_dir: str | Path) -> "ComparableCaseIndex":
        output_dir = Path(output_dir)
        return cls(
            pd.read_parquet(output_dir / "comparable_cases.parquet"),
            joblib.load(output_dir / "comparable_vectorizer.joblib"),
            sparse.load_npz(output_dir / "comparable_tfidf.npz").tocsr(),
        )

    def search(
        self,
        query: str,
        top_n: int = 5,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
        authority: str | None = None,
        app_type: str | None = None,
        exclude_application_id: str | None = None,
        geographical_first: bool = False,
        housing_only: bool = False,
        min_similarity: float = 0.0,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query or self.matrix.shape[0] == 0:
            return []
        q = self.vectorizer.transform([query])
        scores = np.asarray((self.matrix @ q.T).toarray()).ravel()
        mask = np.ones(len(self.metadata), dtype=bool)
        if authority:
            mask &= self.metadata["authority"].fillna("").eq(authority).to_numpy()
        if app_type:
            mask &= self.metadata["app_type"].fillna("").eq(app_type).to_numpy()
        if exclude_application_id:
            mask &= self.metadata["application_id"].ne(exclude_application_id).to_numpy()

        distances = np.full(len(self.metadata), np.nan, dtype=float)
        if lat is not None and lon is not None:
            valid = self.metadata["lat"].notna() & self.metadata["lon"].notna()
            distances[valid.to_numpy()] = haversine_m(
                self.metadata.loc[valid, "lat"], self.metadata.loc[valid, "lon"], lat, lon
            )
            if radius_m is not None:
                mask &= np.nan_to_num(distances, nan=np.inf) <= float(radius_m)

        mask &= scores >= float(min_similarity)
        candidates = np.flatnonzero(mask)
        if not len(candidates):
            return []

        if geographical_first and lat is not None and lon is not None:
            authority_values = self.metadata["authority"].fillna("").to_numpy()
            target_authority = authority or ""
            # Geography is a filter/bucket first; semantic score resolves ties.
            bucket = np.where(np.nan_to_num(distances[candidates], nan=np.inf) <= 1000, 0,
                     np.where(np.nan_to_num(distances[candidates], nan=np.inf) <= 5000, 1, 2))
            same_authority = (target_authority != "") & (authority_values[candidates] == target_authority)
            order = np.lexsort((-scores[candidates], bucket, ~same_authority))
        else:
            order = np.argsort(-scores[candidates])

        results = []
        query_terms = housing_terms(query)
        for idx in candidates[order]:
            row = self.metadata.iloc[int(idx)]
            candidate_terms = housing_terms(row.get("description"))
            matched_terms = sorted(query_terms & candidate_terms)
            if query_terms and not matched_terms:
                # Prevent generic words such as "new", "change" or "works"
                # from turning unrelated commercial applications into comparables.
                continue
            score = float(scores[idx])
            quality = "strong" if score >= 0.25 else ("moderate" if score >= 0.15 else "weak")
            result = {
                "application_id": _json_value(row.get("application_id")),
                "authority": _json_value(row.get("authority")),
                "address_text": _json_value(row.get("address_text")),
                "description": _json_value(row.get("description")),
                "app_type": _json_value(row.get("app_type")),
                "status": _json_value(row.get("status")),
                "decision": _json_value(row.get("decision")),
                "decision_date": _json_value(row.get("decision_date")),
                "days_to_decision": _json_value(row.get("days_to_decision")),
                "lat": _json_value(row.get("lat")),
                "lon": _json_value(row.get("lon")),
                "source_url": _json_value(row.get("source_url")),
                "similarity_score": round(score, 4),
                "similarity_match_quality": quality,
                "matched_development_terms": matched_terms,
                "decision_category": decision_category(row.get("decision"), row.get("status")),
                "housing_related": is_housing_related(row.get("description")),
            }
            if np.isfinite(distances[idx]):
                result["distance_m"] = round(float(distances[idx]), 1)
            results.append(result)
            if len(results) >= top_n:
                break
        return results
