"""CLI entry point for local, review-only website scans."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from .website_scan import ScanStatus, scan_website


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch one public HTML page and extract unreviewed business facts.")
    parser.add_argument("url", help="Absolute public HTTP(S) URL")
    parser.add_argument("--output", required=True, help="Explicit JSON output path")
    args = parser.parse_args(argv)
    result = asyncio.run(scan_website(args.url))
    try:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print("Could not write the scan result to the requested output path.", file=sys.stderr)
        return 3
    print(f"{result.status.value}: wrote scan result to {args.output}")
    if result.status == ScanStatus.SUCCESS:
        return 0
    if result.status == ScanStatus.PARTIAL:
        return 1
    if result.status == ScanStatus.BLOCKED_BY_POLICY:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
