"""Generate a traceable creative and render it through the existing renderer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .creative import GenerationStatus, generate_creative, to_renderer_input
from .facts import BusinessFacts
from .renderer import render_ad
from .validation import RendererError


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a fact-grounded local AdForge creative.")
    parser.add_argument("--input", required=True, type=Path, help="Business facts JSON file")
    parser.add_argument("--creative-output", required=True, type=Path,
                        help="Generated creative JSON path")
    parser.add_argument("--output", required=True, type=Path, help="Destination MP4 path")
    args = parser.parse_args()
    try:
        facts = BusinessFacts.model_validate_json(args.input.read_text(encoding="utf-8"))
        result = generate_creative(facts)
        args.creative_output.parent.mkdir(parents=True, exist_ok=True)
        args.creative_output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        if result.status == GenerationStatus.NEEDS_REVIEW:
            print(result.model_dump_json(indent=2), file=sys.stderr)
            return 2
        renderer_input = to_renderer_input(result.creative, facts)
        metadata = render_ad(renderer_input, args.output)
    except (OSError, ValidationError, ValueError, RendererError) as exc:
        print(f"Creative render failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"creative_output": str(args.creative_output.resolve()),
                      "video_output": str(args.output.resolve()),
                      "warnings": result.warnings, **metadata}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
