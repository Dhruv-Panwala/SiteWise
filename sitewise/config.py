from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def _path(value: str | None, root: Path, default: str) -> Path:
    candidate = Path(value or default)
    return candidate if candidate.is_absolute() else root / candidate


@dataclass(frozen=True)
class Settings:
    root: Path
    planning_csv: Path
    processed_dir: Path
    cache_dir: Path
    planning_data_api: str
    enable_live_constraints: bool
    request_timeout_seconds: int
    cache_ttl_seconds: int
    constraint_geojson_dir: Path
    hf_token: str | None
    hf_model: str
    hf_provider: str
    hf_max_new_tokens: int
    hf_temperature: float
    hf_max_nearby_cases: int
    hf_max_similar_cases: int
    hf_max_description_chars: int
    hf_max_input_chars: int
    enable_gla_arcgis: bool = False
    arcgis_services_base: str = "https://services.arcgis.com/drifeOPKLpgnJ8Qa/arcgis/rest/services"

    @classmethod
    def from_env(cls, root: Path | None = None, *, load_env_file: bool = True) -> "Settings":
        root = (root or ROOT).resolve()
        if load_env_file:
            load_dotenv(root / ".env")
        return cls(
            root=root,
            planning_csv=_path(os.getenv("PLANNING_CSV"), root, "Data/raw/foundations_london_housing_2022_2025_20260810T013626Z.csv"),
            processed_dir=_path(os.getenv("PROCESSED_DIR"), root, "data/processed"),
            cache_dir=_path(os.getenv("CACHE_DIR"), root, "data/cache"),
            planning_data_api=os.getenv("PLANNING_DATA_API", "https://www.planning.data.gov.uk/entity.json"),
            enable_live_constraints=os.getenv("ENABLE_LIVE_CONSTRAINTS", "false").lower() in {"1", "true", "yes"},
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "86400")),
            constraint_geojson_dir=_path(os.getenv("CONSTRAINT_GEOJSON_DIR"), root, "data/raw/constraints"),
            hf_token=os.getenv("HF_TOKEN") or None,
            hf_model=os.getenv("HF_MODEL", "microsoft/Phi-4-mini-instruct"),
            hf_provider=os.getenv("HF_PROVIDER", "featherless-ai"),
            hf_max_new_tokens=int(os.getenv("HF_MAX_NEW_TOKENS", "450")),
            hf_temperature=float(os.getenv("HF_TEMPERATURE", "0.2")),
            hf_max_nearby_cases=int(os.getenv("HF_MAX_NEARBY_CASES", "4")),
            hf_max_similar_cases=int(os.getenv("HF_MAX_SIMILAR_CASES", "3")),
            hf_max_description_chars=int(os.getenv("HF_MAX_DESCRIPTION_CHARS", "320")),
            hf_max_input_chars=int(os.getenv("HF_MAX_INPUT_CHARS", "12000")),
            enable_gla_arcgis=os.getenv("ENABLE_GLA_ARCGIS", "false").lower() in {"1", "true", "yes"},
            arcgis_services_base=os.getenv("ARCGIS_SERVICES_BASE", "https://services.arcgis.com/drifeOPKLpgnJ8Qa/arcgis/rest/services").rstrip("/"),
        )
