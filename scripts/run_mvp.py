from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitewise.config import Settings
from sitewise.evidence import EvidenceService
from sitewise.llm import generate_report
from sitewise.planning import ensure_prepared
from sitewise.similarity import ComparableCaseIndex


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SiteWise UK deterministic evidence MVP")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--description", default="", help="Proposed development description for comparable-case search")
    parser.add_argument("--app-type", default=None)
    parser.add_argument("--authority", default=None)
    parser.add_argument("--radius-m", type=float, default=1000)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--print-llm-context", action="store_true", help="Print each non-secret LLM request context to stderr")
    parser.add_argument("--gla", action="store_true", help="Enable GLA local-plan spatial retrieval")
    parser.add_argument("--no-env-file", action="store_true", help="Use defaults/process variables without reading .env")
    args = parser.parse_args()
    settings = Settings.from_env(load_env_file=not args.no_env_file)
    if args.gla:
        settings = replace(settings, enable_gla_arcgis=True)

    prepared_path = settings.processed_dir / "planning_applications.parquet"
    index_dir = settings.processed_dir / "comparable_index"
    applications = ensure_prepared(settings.planning_csv, prepared_path)
    required_index = ["comparable_cases.parquet", "comparable_tfidf.npz", "comparable_vectorizer.joblib"]
    if not all((index_dir / name).exists() for name in required_index):
        ComparableCaseIndex.build(applications, index_dir)
    index = ComparableCaseIndex.load(index_dir)
    service = EvidenceService(applications, index, settings=settings)
    evidence = service.analyze(
        args.lat,
        args.lon,
        description=args.description,
        app_type=args.app_type,
        authority=args.authority,
        radius_m=args.radius_m,
        top_n=args.top_n,
    )
    if not args.no_llm:
        evidence["llm_report"] = generate_report(evidence, settings, debug_print_context=args.print_llm_context)
    print(json.dumps(evidence, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
