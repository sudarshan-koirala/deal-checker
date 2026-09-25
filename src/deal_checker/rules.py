"""Your rules. Plain Python. No AI.

The model reads the contract. Your rules decide what is a red flag.
Change the numbers to match your own standards.
"""

from dataclasses import dataclass

from .schema import DealTerms

MAX_PAYMENT_DAYS = 45  # get paid within 45 days
MAX_EXCLUSIVITY_DAYS = 30  # block competitors for 30 days at most
MAX_REVISION_ROUNDS = 2  # two rounds of changes is fair


@dataclass
class Flag:
    field: str  # the DealTerms field behind the flag (used to find the page)
    message: str


def total_exclusivity_days(terms: DealTerms) -> int:
    return (terms.exclusivity_during_days or 0) + (terms.exclusivity_after_days or 0)


def check_deal(terms: DealTerms) -> list[Flag]:
    flags: list[Flag] = []

    if terms.perpetual_rights_quote:
        flags.append(Flag("perpetual_rights_quote", "Perpetual rights: the brand can use your content forever"))

    if terms.face_in_paid_ads_quote:
        flags.append(Flag("face_in_paid_ads_quote", "Your face and voice can appear in their paid ads"))

    exclusivity = total_exclusivity_days(terms)
    if exclusivity > MAX_EXCLUSIVITY_DAYS:
        # cite whichever clause contributes more, since each has its own citation
        field = "exclusivity_after_days" if (terms.exclusivity_after_days or 0) >= (terms.exclusivity_during_days or 0) else "exclusivity_during_days"
        flags.append(Flag(field, f"Long exclusivity: {exclusivity} days"))

    if terms.payment_days and terms.payment_days > MAX_PAYMENT_DAYS:
        flags.append(Flag("payment_days", f"Slow payment: Net {terms.payment_days}"))

    if terms.unlimited_revisions_quote:
        flags.append(Flag("unlimited_revisions_quote", "Unlimited revisions until the brand approves"))
    elif terms.revision_rounds and terms.revision_rounds > MAX_REVISION_ROUNDS:
        flags.append(Flag("revision_rounds", f"{terms.revision_rounds} revision rounds"))

    return flags
