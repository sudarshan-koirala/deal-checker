"""Command line entry point.

    uv run deal-checker                      # checks sample_contracts/
    uv run deal-checker ~/Downloads/deals    # any folder
    uv run deal-checker contract.pdf --tier cost_effective
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader

from .report import print_summary
from .workflow import TIERS, CheckDeals, Progress, workflow

SUPPORTED = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
CREDITS_PER_PAGE = {"cost_effective": 8, "agentic": 25, "agentic_plus": 95}  # parse + extract


def collect(inputs: list[str]) -> list[str]:
    sources: list[str] = []
    for item in inputs:
        if item.startswith(("http://", "https://")):
            sources.append(item)
            continue
        path = Path(item).expanduser()
        if path.is_dir():
            sources += [str(f) for f in sorted(path.iterdir()) if f.suffix.lower() in SUPPORTED]
        elif path.is_file():
            sources.append(str(path))
        else:
            sys.exit(f"Not found: {item}")
    return sources


def estimate(sources: list[str], tier: str) -> str:
    pages = 0
    for source in sources:
        if source.lower().endswith(".pdf") and not source.startswith("http"):
            pages += len(PdfReader(source).pages)
        else:
            pages += 1  # images count as one page; other types are a guess
    credits = pages * CREDITS_PER_PAGE[tier]
    return f"{len(sources)} contracts, about {pages} pages. Estimated cost: {credits:,} credits ({tier})."


async def run(sources: list[str], tier: str, out_dir: str):
    handler = workflow.run(start_event=CheckDeals(sources=sources, tier=tier, out_dir=out_dir))
    async for ev in handler.stream_events():
        if isinstance(ev, Progress):
            print(f"  {ev.message}")
    return await handler


def main() -> None:
    parser = argparse.ArgumentParser(prog="deal-checker", description="Flag bad terms in brand deal contracts.")
    parser.add_argument("inputs", nargs="*", default=["sample_contracts"], help="folders, files or URLs")
    parser.add_argument("--tier", choices=list(TIERS), default="agentic")
    parser.add_argument("--out", default="reports", help="where to save the report")
    args = parser.parse_args()

    load_dotenv()
    if not os.getenv("LLAMA_CLOUD_API_KEY"):
        sys.exit("Missing LLAMA_CLOUD_API_KEY. Copy .env.example to .env and paste your key.")

    sources = collect(args.inputs)
    if not sources:
        sys.exit("No contracts found.")
    print(estimate(sources, args.tier))
    report = asyncio.run(run(sources, args.tier, args.out))
    print_summary(report.deals, report.report_path)


if __name__ == "__main__":
    main()
