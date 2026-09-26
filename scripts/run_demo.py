from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitewise.webapp import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SiteWise UK map demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--prompt-hf-token", action="store_true", help="Prompt securely for HF_TOKEN in memory; never read or write .env")
    args = parser.parse_args()
    if args.prompt_hf_token:
        token = getpass.getpass("Hugging Face token (hidden, this process only): ").strip()
        if token:
            os.environ["HF_TOKEN"] = token
    create_app().run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
