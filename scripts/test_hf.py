from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from huggingface_hub import HfApi, InferenceClient

from sitewise.config import Settings


DEFAULT_QUESTION = "How do banks earn money? Answer in three short bullet points."


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the Hugging Face token and Phi-4 Mini inference")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.hf_token:
        print("HF_TOKEN is missing. Add it to .env, then run this script again.")
        return 1

    try:
        profile = HfApi(token=settings.hf_token).whoami()
        print(f"Token accepted for Hugging Face account: {profile.get('name', 'unknown')}")
    except Exception as exc:
        message = str(exc).replace(settings.hf_token, "[REDACTED]")
        print(f"Token validation failed ({exc.__class__.__name__}): {message}")
        return 1

    try:
        client = InferenceClient(
            provider=settings.hf_provider,
            api_key=settings.hf_token,
        )
        response = client.chat.completions.create(
            model=settings.hf_model,
            messages=[{"role": "user", "content": args.question}],
            max_tokens=180,
            temperature=0.2,
        )
        answer = response.choices[0].message.content if response.choices else None
        if not answer:
            print("The token worked, but the model returned no answer.")
            return 1
        print(f"\nModel: {settings.hf_model}\n")
        print(answer.strip())
        return 0
    except Exception as exc:
        message = str(exc).replace(settings.hf_token, "[REDACTED]")
        print(f"The token is valid, but model inference failed ({exc.__class__.__name__}): {message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
