"""Turn checked deals into a Markdown report, a CSV file and a console summary."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

DISCLAIMER = "Not legal advice. Deal Checker finds terms to question. Always read the full contract."


def money(value) -> str:
    return f"${value:,.0f}" if value else "?"


def net(days) -> str:
    return f"Net {days}" if days else "?"


def span(days) -> str:
    if days is None:
        return "?"
    return "none" if days == 0 else f"{days} days"


def exclusivity_total(t: dict) -> int | None:
    during, after = t.get("exclusivity_during_days"), t.get("exclusivity_after_days")
    if during is None and after is None:
        return None
    return (during or 0) + (after or 0)


def brand(deal: dict) -> str:
    return (deal["terms"] or {}).get("brand_name") or deal["file"]


def save_markdown(out_dir: str, name: str, pages: list[str]) -> None:
    """Keep what LlamaParse read, so you can check it yourself."""
    folder = Path(out_dir) / "parsed"
    folder.mkdir(parents=True, exist_ok=True)
    text = "\n\n".join(f"<!-- page {i} -->\n{page}" for i, page in enumerate(pages, 1))
    (folder / f"{Path(name).stem}.md").write_text(text, encoding="utf-8")


def save_metadata(out_dir: str, name: str, raw: dict) -> None:
    """Keep the raw per-field metadata LlamaParse Extract returned, so a missing
    citation (no page/quote for a flag) can be checked against what the API actually sent."""
    folder = Path(out_dir) / "parsed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{Path(name).stem}.metadata.json").write_text(json.dumps(raw, indent=2, default=str), encoding="utf-8")


def write_report(deals: list[dict], out_dir: str) -> Path:
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Deal Checker report",
        "",
        f"{len(deals)} contracts checked on {date.today():%B %d, %Y}.",
        "",
        "| Brand | Fee | Pages | Payment | Exclusivity | Red flags |",
        "|---|---|---|---|---|---|",
    ]
    for d in deals:
        t = d["terms"] or {}
        lines.append(
            f"| {brand(d)} | {money(t.get('fee_usd'))} | {d['pages']} | {net(t.get('payment_days'))} "
            f"| {span(exclusivity_total(t))} | {len(d['flags'])} |"
        )
    for d in deals:
        lines += ["", f"## {brand(d)}", f"`{d['file']}`", ""]
        if d["error"]:
            lines.append(f"- Could not check this file: {d['error']}")
        elif not d["flags"]:
            lines.append("- ✅ No red flags found.")
        for f in d["flags"]:
            where = f" (page {f['page']})" if f.get("page") else ""
            lines.append(f"- 🚩 {f['message']}{where}")
            if f.get("quote"):
                lines.append(f'  > "{f["quote"]}"')
    lines += ["", f"_{DISCLAIMER}_", ""]
    path = folder / "deal_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    write_csv(deals, folder / "deals.csv")
    return path


def write_csv(deals: list[dict], path: Path) -> None:
    columns = ["file", "brand", "fee_usd", "pages", "payment_days", "usage_days", "exclusivity_days",
               "perpetual_rights", "face_in_paid_ads", "unlimited_revisions", "red_flags", "flags", "error"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for d in deals:
            t = d["terms"] or {}
            writer.writerow({
                "file": d["file"], "brand": brand(d), "fee_usd": t.get("fee_usd"), "pages": d["pages"],
                "payment_days": t.get("payment_days"), "usage_days": t.get("usage_days"),
                "exclusivity_days": exclusivity_total(t), "perpetual_rights": bool(t.get("perpetual_rights_quote")),
                "face_in_paid_ads": bool(t.get("face_in_paid_ads_quote")),
                "unlimited_revisions": bool(t.get("unlimited_revisions_quote")),
                "red_flags": len(d["flags"]), "flags": " | ".join(f["message"] for f in d["flags"]),
                "error": d["error"],
            })


def print_summary(deals: list[dict], report_path: str) -> None:
    print(f"\nDeal Checker: {len(deals)} contracts\n")
    for d in deals:
        fee = money((d["terms"] or {}).get("fee_usd"))
        if d["error"]:
            status = "could not check"
        elif d["flags"]:
            status = f"🚩 {len(d['flags'])} red flags"
        else:
            status = "✅ no red flags"
        print(f"  {brand(d):<28}{fee:>9}   {status}")
        for f in d["flags"]:
            where = f"page {f['page']}" if f.get("page") else ""
            print(f"      {f['message']:<58}{where}")
            if f.get("quote"):
                quote = f["quote"] if len(f["quote"]) <= 70 else f["quote"][:67] + "..."
                print(f'        "{quote}"')
        if d["error"]:
            print(f"      {d['error']}")
    print(f"\n  Full report: {report_path}\n  {DISCLAIMER}\n")
