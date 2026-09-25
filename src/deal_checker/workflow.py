"""The Deal Checker workflow.

    CheckDeals -> parse -> extract -> check -> report -> DealReport

parse and extract run on LlamaParse. check and report are plain Python.
"""

from __future__ import annotations

from pathlib import Path

from llama_cloud import AsyncLlamaCloud
from pydantic import ValidationError
from workflows import Context, Workflow, step
from workflows.events import Event, StartEvent, StopEvent

from .report import save_markdown, save_metadata, write_report
from .rules import check_deal
from .schema import DealTerms

# tier name -> (parse tier, extract tier). Agentic is a good default.
TIERS = {
    "cost_effective": ("cost_effective", "cost_effective"),
    "agentic": ("agentic", "agentic"),
    "agentic_plus": ("agentic", "agentic_plus"),
}
VERSION = "latest"  # pin a date, for example "2026-09-14", in production

# Ask for job status less often (the free plan allows 20 requests a minute).
POLL = {"polling_interval": 2.0, "max_interval": 10.0, "backoff": "exponential"}

EXTRACT_PROMPT = (
    "This is a creator sponsorship contract. Read every page, including exhibits, "
    "schedules and small print. If a summary table disagrees with a detailed clause "
    "or exhibit, report what the detailed clause says."
)


# ------------------------------------------------------------------ events
class CheckDeals(StartEvent):
    sources: list[str]  # local file paths or https:// URLs
    tier: str = "agentic"
    out_dir: str = "reports"


class Progress(Event):
    message: str


class ContractFound(Event):
    source: str


class ContractParsed(Event):
    source: str
    parse_job_id: str
    pages: int


class DealExtracted(Event):
    source: str
    pages: int
    terms: dict
    citations: dict


class DealChecked(Event):
    deal: dict


class DealReport(StopEvent):
    deals: list[dict]
    report_path: str = ""


# ---------------------------------------------------------------- workflow
class DealCheckWorkflow(Workflow):
    """Reads every contract, pulls out the terms and flags the bad ones."""

    def __init__(self, client: AsyncLlamaCloud | None = None, **kwargs):
        super().__init__(**kwargs)
        self._client = client

    @property
    def client(self) -> AsyncLlamaCloud:
        # Made on first use, so importing this file never needs an API key.
        if self._client is None:
            self._client = AsyncLlamaCloud()  # reads LLAMA_CLOUD_API_KEY
        return self._client

    @step
    async def start(self, ctx: Context, ev: CheckDeals) -> ContractFound | DealReport | None:
        if ev.tier not in TIERS:
            raise ValueError(f"tier must be one of: {', '.join(TIERS)}")
        if not ev.sources:
            return DealReport(deals=[])
        await ctx.store.set("expected", len(ev.sources))
        await ctx.store.set("tier", ev.tier)
        await ctx.store.set("out_dir", ev.out_dir)
        for source in ev.sources:
            ctx.send_event(ContractFound(source=source))
        return None

    @step(num_workers=2)  # two contracts at a time
    async def parse(self, ctx: Context, ev: ContractFound) -> ContractParsed | DealChecked:
        name = Path(ev.source).name
        ctx.write_event_to_stream(Progress(message=f"Reading    {name}"))
        parse_tier, _ = TIERS[await ctx.store.get("tier")]
        try:
            if ev.source.startswith(("http://", "https://")):
                result = await self.client.parsing.parse(
                    source_url=ev.source, tier=parse_tier, version=VERSION, expand=["markdown"], **POLL
                )
            else:
                result = await self.client.parsing.parse(
                    upload_file=Path(ev.source), tier=parse_tier, version=VERSION, expand=["markdown"], **POLL
                )
        except Exception as err:  # one bad file must not stop the others
            return DealChecked(deal=failed(ev.source, f"parse failed: {err}"))

        pages = [p.markdown for p in result.markdown.pages if getattr(p, "markdown", None)]
        save_markdown(await ctx.store.get("out_dir"), name, pages)
        ctx.write_event_to_stream(Progress(message=f"Parsed     {name} ({len(pages)} pages)"))
        return ContractParsed(source=ev.source, parse_job_id=result.job.id, pages=len(pages))

    @step(num_workers=2)
    async def extract(self, ctx: Context, ev: ContractParsed) -> DealExtracted | DealChecked:
        name = Path(ev.source).name
        _, extract_tier = TIERS[await ctx.store.get("tier")]
        try:
            job = await self.client.extract.run(
                file_input=ev.parse_job_id,  # reuse the parse: no second parse charge
                configuration={
                    "data_schema": DealTerms.model_json_schema(),
                    "tier": extract_tier,
                    "version": VERSION,
                    "system_prompt": EXTRACT_PROMPT,
                    "cite_sources": True,  # page number + exact words for every field
                },
                **POLL,
            )
            # run() returns the finished job WITHOUT the per-field metadata.
            # Ask for it by name, or you get no page numbers and no quotes.
            # This is a plain GET. It costs no credits.
            job = await self.client.extract.get(job.id, expand=["extract_metadata", "usage"])
        except Exception as err:
            return DealChecked(deal=failed(ev.source, f"extract failed: {err}"))
        raw_metadata = raw_field_metadata(job)
        save_metadata(await ctx.store.get("out_dir"), name, raw_metadata)
        ctx.write_event_to_stream(Progress(message=f"Extracted  {name}"))
        return DealExtracted(
            source=ev.source,
            pages=ev.pages,
            terms=job.extract_result or {},
            citations=citations_from(raw_metadata),
        )

    @step
    async def check(self, ev: DealExtracted) -> DealChecked:
        try:
            terms = DealTerms.model_validate(ev.terms)
        except ValidationError as err:
            return DealChecked(deal=failed(ev.source, f"unexpected terms ({err.error_count()} errors)"))
        flags = [{"message": f.message, **ev.citations.get(f.field, {})} for f in check_deal(terms)]
        return DealChecked(
            deal={
                "file": Path(ev.source).name,
                "pages": ev.pages,
                "terms": terms.model_dump(),
                "flags": flags,
                "error": None,
            }
        )

    @step
    async def report(self, ctx: Context, ev: DealChecked) -> DealReport | None:
        expected = await ctx.store.get("expected")
        done = ctx.collect_events(ev, [DealChecked] * expected)
        if done is None:
            return None  # wait until every contract is checked
        deals = sorted((d.deal for d in done), key=fee_of, reverse=True)
        path = write_report(deals, await ctx.store.get("out_dir"))
        return DealReport(deals=deals, report_path=str(path))


# ----------------------------------------------------------------- helpers
def raw_field_metadata(job) -> dict:
    """The per-field metadata Extract returned, straight off the wire (for debugging
    and for citations_from). Saved to reports/parsed/<file>.metadata.json on every run."""
    meta = getattr(job, "extract_metadata", None)
    if meta is None or meta.field_metadata is None:
        return {}
    return meta.field_metadata.model_dump()


def citations_from(raw: dict) -> dict:
    """field name -> {"page": 29, "quote": "exact words"} from Extract citations.

    Not every field gets one back: cite_sources only attaches a citation when the
    model can point to a single verbatim span, so a boolean synthesized from several
    clauses (or a value that's a sum of two clauses) can come back with no citation
    at all, even though the field's value itself is correct."""
    fields = raw.get("document_metadata") or raw
    cites = {}
    for field, info in fields.items():
        found = info.get("citation") if isinstance(info, dict) else None
        if found and isinstance(found[0], dict):
            cites[field] = {
                "page": found[0].get("page"),
                "quote": (found[0].get("matching_text") or "").strip(),
            }
    return cites


def failed(source: str, error: str) -> dict:
    return {"file": Path(source).name, "pages": 0, "terms": None, "flags": [], "error": error}


def fee_of(deal: dict) -> float:
    return (deal.get("terms") or {}).get("fee_usd") or 0


# The CLI and `llamactl serve` both use this instance.
workflow = DealCheckWorkflow(timeout=1800)  # big contracts can take a few minutes
