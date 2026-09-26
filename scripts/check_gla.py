"""Public GLA retrieval diagnostic: deliberately never loads .env or an LLM."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitewise.arcgis import GLALocalPlanClient
from sitewise.config import ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lon", required=True, type=float)
    parser.add_argument("--authority", help="Optional London borough, LLDC or OPDC; otherwise check all service extents")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data/cache")
    parser.add_argument("--refresh", action="store_true", help="Ignore previously cached API responses")
    args = parser.parse_args()
    client = GLALocalPlanClient(args.cache_dir, cache_ttl=0 if args.refresh else 86400)
    result = client.analyze(args.lat, args.lon, authority=args.authority)
    print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    return 0 if result["status"] in {"complete", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
