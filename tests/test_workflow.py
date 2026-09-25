"""End-to-end test with a fake LlamaParse client. No API key, no credits."""

from pathlib import Path
from types import SimpleNamespace

from deal_checker.cli import estimate
from deal_checker.workflow import CheckDeals, DealCheckWorkflow, DealReport

SAMPLES = sorted(str(p) for p in (Path(__file__).parent.parent / "sample_contracts").glob("*.pdf"))

# What a good extraction returns for each sample, checked by hand against the PDFs.
# field -> (page, exact words) is what cite_sources gives back. Quote fields carry
# the citation's own text as their value, since that's what makes them citable at all.
PERPETUAL_QUOTE = "perpetual, irrevocable, worldwide, royalty-free license"
FACE_IN_ADS_QUOTE = "Creator's name, likeness, image, voice and biographical information, in Paid Media"
UNLIMITED_REVISIONS_QUOTE = "continue to revise the Deliverable until Brand approves it in writing"

EXPECTED = {
    "pixelpilot_master_agreement.pdf": (
        dict(brand_name="PixelPilot Networks Ltd.", fee_usd=18000, payment_days=30, usage_days=60,
             perpetual_rights_quote=PERPETUAL_QUOTE, face_in_paid_ads_quote=FACE_IN_ADS_QUOTE,
             exclusivity_during_days=181, exclusivity_after_days=365,
             revision_rounds=None, unlimited_revisions_quote=UNLIMITED_REVISIONS_QUOTE),
        {"perpetual_rights_quote": (31, PERPETUAL_QUOTE),
         "face_in_paid_ads_quote": (31, FACE_IN_ADS_QUOTE),
         "exclusivity_after_days": (8, "for twelve (12) months after the expiry or termination of this Agreement"),
         "unlimited_revisions_quote": (13, UNLIMITED_REVISIONS_QUOTE)},
    ),
    "lumora_sponsorship.pdf": (
        dict(brand_name="Lumora Lighting Co.", fee_usd=2500, payment_days=60, usage_days=90,
             perpetual_rights_quote=None, face_in_paid_ads_quote=None,
             exclusivity_during_days=0, exclusivity_after_days=90,
             revision_rounds=2, unlimited_revisions_quote=None),
        {"exclusivity_after_days": (1, "For ninety (90) days after go-live"),
         "payment_days": (1, "within sixty (60) days of receiving Creator's invoice (Net 60)")},
    ),
    "brewtide_signed_scan.pdf": (
        dict(brand_name="Brewtide Coffee Co.", fee_usd=1800, payment_days=15, usage_days=30,
             perpetual_rights_quote=None, face_in_paid_ads_quote=None,
             exclusivity_during_days=14, exclusivity_after_days=0,
             revision_rounds=1, unlimited_revisions_quote=None),
        {},
    ),
}


class FakeFieldMetadata:
    def __init__(self, cites):
        self._cites = cites

    def model_dump(self):
        return {"document_metadata": {
            field: {"citation": [{"page": page, "matching_text": text}]} for field, (page, text) in self._cites.items()
        }}


class FakeClient:
    def __init__(self, broken: str | None = None):
        self.parsing = SimpleNamespace(parse=self._parse)
        self.extract = SimpleNamespace(run=self._extract, get=self._extract_get)
        self.extract_inputs: list[str] = []
        self.broken = broken
        self.expands: list[list[str]] = []

    async def _parse(self, *, tier, version, expand, upload_file=None, source_url=None, **_):
        name = Path(upload_file).name if upload_file else source_url.rsplit("/", 1)[-1]
        if name == self.broken:
            raise RuntimeError("simulated network error")
        pages = [SimpleNamespace(markdown=f"page {i} of {name}") for i in range(1, 4)]
        return SimpleNamespace(job=SimpleNamespace(id=f"pjb-{name}"), markdown=SimpleNamespace(pages=pages))

    async def _extract(self, *, file_input, configuration, **_):
        """Like the real run(): the result carries NO per-field metadata."""
        self.extract_inputs.append(file_input)
        terms, _ = EXPECTED[file_input.removeprefix("pjb-")]
        return SimpleNamespace(id=f"ejb-{file_input}", extract_result=terms, extract_metadata=None)

    async def _extract_get(self, job_id, *, expand=(), **_):
        """Citations arrive only when the caller asks for extract_metadata."""
        self.expands.append(list(expand))
        source = job_id.removeprefix("ejb-pjb-")
        terms, cites = EXPECTED[source]
        meta = None
        if "extract_metadata" in expand:
            meta = SimpleNamespace(field_metadata=FakeFieldMetadata(cites))
        return SimpleNamespace(id=job_id, extract_result=terms, extract_metadata=meta)


async def test_flags_the_right_deals(tmp_path):
    client = FakeClient()
    wf = DealCheckWorkflow(client=client, timeout=60)
    report = await wf.run(start_event=CheckDeals(sources=SAMPLES, out_dir=str(tmp_path)))

    assert isinstance(report, DealReport)
    assert [d["file"] for d in report.deals] == [  # biggest fee first
        "pixelpilot_master_agreement.pdf", "lumora_sponsorship.pdf", "brewtide_signed_scan.pdf"]
    assert [len(d["flags"]) for d in report.deals] == [4, 2, 0]

    # Every flag must carry its evidence. This is what makes the report checkable.
    top = report.deals[0]["flags"][0]
    assert top["page"] == 31 and "perpetual" in top["quote"]
    assert all(f.get("page") for d in report.deals for f in d["flags"])
    assert all("extract_metadata" in e for e in client.expands)
    assert all(i.startswith("pjb-") for i in client.extract_inputs)  # extract reuses the parse job
    assert (tmp_path / "deal_report.md").exists() and (tmp_path / "deals.csv").exists()

    # Raw per-field metadata is kept on disk, so a flag missing a page/quote can be
    # checked against what Extract actually returned instead of guessing.
    metadata_path = tmp_path / "parsed" / "pixelpilot_master_agreement.metadata.json"
    assert metadata_path.exists()
    assert "document_metadata" in metadata_path.read_text()


async def test_one_broken_file_does_not_stop_the_run(tmp_path):
    wf = DealCheckWorkflow(client=FakeClient(broken="lumora_sponsorship.pdf"), timeout=60)
    report = await wf.run(start_event=CheckDeals(sources=SAMPLES, out_dir=str(tmp_path)))
    errors = {d["file"]: d["error"] for d in report.deals}
    assert "simulated network error" in errors["lumora_sponsorship.pdf"]
    assert errors["pixelpilot_master_agreement.pdf"] is None


def test_cost_estimate_for_the_samples():
    assert estimate(SAMPLES, "agentic") == "3 contracts, about 35 pages. Estimated cost: 875 credits (agentic)."
