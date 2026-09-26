"""Read-only live check of council text; never loads .env or calls an LLM."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sitewise.config import Settings
from sitewise.policies import CouncilPolicyClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, default=51.47914)
    parser.add_argument("--lon", type=float, default=-0.16682)
    parser.add_argument("--description", default="Rear extension to an existing house and two new homes")
    args = parser.parse_args()
    result = CouncilPolicyClient(Settings.from_env(load_env_file=False)).retrieve(args.lat, args.lon, args.description)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["items"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
