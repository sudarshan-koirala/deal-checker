"""What we want LlamaParse Extract to read from each contract.

Every description is an instruction to the extraction model.
Clear descriptions beat clever code.

Fields are quotes and plain numbers, not booleans or sums. cite_sources only
reliably attaches a page/quote citation when a field maps to one verbatim span
in the text - a boolean synthesized from "any clause anywhere" or a number that's
the sum of two clauses has no single span to cite, so the API tends to return no
citation for those at all. rules.py derives the booleans and totals from these.
"""

from pydantic import BaseModel, Field


class DealTerms(BaseModel):
    brand_name: str = Field(
        description="Name of the brand or company that pays the creator."
    )
    fee_usd: float | None = Field(
        default=None,
        description="Total fee for the whole agreement in US dollars, as a plain number. Example: 18000.",
    )
    deliverables: list[str] = Field(
        default_factory=list,
        description="Each piece of content the creator must publish, one short line each.",
    )
    payment_days: int | None = Field(
        default=None,
        description="Days until the creator gets paid after invoice or go-live. 'Net 60' means 60.",
    )
    usage_days: int | None = Field(
        default=None,
        description="Days the brand may repost the content organically, as stated in the usage rights clause.",
    )
    perpetual_rights_quote: str | None = Field(
        default=None,
        description="The exact sentence, copied verbatim from ANY clause, exhibit or schedule, that gives the "
        "brand rights to the content in perpetuity, forever or irrevocably. Leave empty if no such clause exists.",
    )
    face_in_paid_ads_quote: str | None = Field(
        default=None,
        description="The exact sentence, copied verbatim, that lets the brand use the creator's name, face, "
        "likeness or voice in paid advertising. Leave empty if no such clause exists.",
    )
    exclusivity_during_days: int | None = Field(
        default=None,
        description="Days the creator may not work with competing brands while this agreement is active, "
        "as a plain number stated in the exclusivity clause. 0 if none.",
    )
    exclusivity_after_days: int | None = Field(
        default=None,
        description="Days after this agreement ends that the creator still may not work with competing brands, "
        "as a plain number stated in the exclusivity clause. 0 if none.",
    )
    revision_rounds: int | None = Field(
        default=None,
        description="Number of revision rounds included. Leave empty if revisions continue until the brand approves.",
    )
    unlimited_revisions_quote: str | None = Field(
        default=None,
        description="The exact sentence, copied verbatim, stating the creator must keep revising until the "
        "brand approves with no limit on rounds. Leave empty if revisions are capped at a number of rounds.",
    )
