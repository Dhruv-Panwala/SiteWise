from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitewise.webapp import SiteWiseDemo, create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SiteWise UK map demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--live-constraints", action="store_true", help="Explicitly enable public Planning Data constraint queries without reading .env")
    parser.add_argument("--prompt-hf-token", action="store_true", help="Prompt securely for HF_TOKEN in memory; never read or write .env")
    args = parser.parse_args()
    if args.live_constraints:
        os.environ["ENABLE_LIVE_CONSTRAINTS"] = "true"
    if args.prompt_hf_token:
        token = getpass.getpass("Hugging Face token (hidden, this process only): ").strip()
        if token:
            os.environ["HF_TOKEN"] = token
    demo = SiteWiseDemo()
    state = "ENABLED" if demo.settings.enable_live_constraints else "DISABLED"
    print(f"Live Planning Data constraints: {state}", flush=True)
    print(f"SiteWise URL: http://{args.host}:{args.port}", flush=True)
    create_app(demo=demo).run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
