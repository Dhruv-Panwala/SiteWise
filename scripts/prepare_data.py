from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitewise.config import Settings
from sitewise.planning import prepare_planning_csv
from sitewise.similarity import ComparableCaseIndex


def main() -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Prepare SiteWise planning data and comparable-case index")
    parser.add_argument("--csv", type=Path, default=settings.planning_csv)
    parser.add_argument("--output", type=Path, default=settings.processed_dir / "planning_applications.parquet")
    parser.add_argument("--index-dir", type=Path, default=settings.processed_dir / "comparable_index")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()

    prepared = prepare_planning_csv(args.csv, args.output, max_rows=args.max_rows)
    summary = {
        "rows": len(prepared),
        "valid_coordinates": int(prepared["coordinate_quality"].eq("valid").sum()),
        "missing_coordinates": int(prepared["coordinate_quality"].eq("missing").sum()),
        "out_of_bounds_coordinates": int(prepared["coordinate_quality"].eq("out_of_bounds").sum()),
        "output": str(args.output),
    }
    if not args.skip_index:
        index = ComparableCaseIndex.build(prepared, args.index_dir)
        summary["index_rows"] = len(index.metadata)
        summary["index_features"] = int(index.matrix.shape[1])
        summary["index_dir"] = str(args.index_dir)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
