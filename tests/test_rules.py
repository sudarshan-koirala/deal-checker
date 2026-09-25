"""The rules are plain Python, so they are easy to test."""

from deal_checker.rules import check_deal
from deal_checker.schema import DealTerms


def terms(**changes) -> DealTerms:
    base = dict(
        brand_name="Brand", fee_usd=1000, payment_days=30, usage_days=30,
        perpetual_rights_quote=None, face_in_paid_ads_quote=None,
        exclusivity_during_days=0, exclusivity_after_days=0,
        revision_rounds=1, unlimited_revisions_quote=None,
    )
    base.update(changes)
    return DealTerms(**base)


def test_clean_deal_has_no_flags():
    assert check_deal(terms()) == []


def test_limits_are_allowed():
    assert check_deal(terms(payment_days=45, exclusivity_during_days=30, revision_rounds=2)) == []


def test_one_over_the_limit_is_flagged():
    messages = [f.message for f in check_deal(terms(payment_days=46, exclusivity_during_days=31, revision_rounds=3))]
    assert messages == ["Long exclusivity: 31 days", "Slow payment: Net 46", "3 revision rounds"]


def test_small_print_flags_come_first():
    flags = check_deal(terms(
        perpetual_rights_quote="forever", face_in_paid_ads_quote="in ads",
        unlimited_revisions_quote="until approved", revision_rounds=None,
    ))
    assert [f.field for f in flags] == ["perpetual_rights_quote", "face_in_paid_ads_quote", "unlimited_revisions_quote"]


def test_missing_numbers_are_not_flagged():
    assert check_deal(terms(payment_days=None, exclusivity_during_days=None, exclusivity_after_days=None, revision_rounds=None)) == []


def test_schema_is_flat_for_extract():
    schema = DealTerms.model_json_schema()
    assert schema["type"] == "object"
    assert "$defs" not in schema
