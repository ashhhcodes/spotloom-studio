"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .models import BusinessInput
from .renderer import render_ad
from .validation import RendererError


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a deterministic AdForge AI MP4.")
    parser.add_argument("--input", required=True, type=Path, help="Business input JSON file")
    parser.add_argument("--output", required=True, type=Path, help="Destination MP4 path")
    args = parser.parse_args()
    try:
        business = BusinessInput.model_validate_json(args.input.read_text(encoding="utf-8"))
        metadata = render_ad(business, args.output)
    except (OSError, ValidationError, RendererError, json.JSONDecodeError) as exc:
        print(f"Render failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output.resolve()), **metadata}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
