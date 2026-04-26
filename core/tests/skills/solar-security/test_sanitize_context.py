from __future__ import annotations

import sanitize_context as mod


def test_sanitize_stable_placeholders_per_normalized_value():
    text = "a@b.com and A@B.COM and +34 612 345 678"
    out, mapping, counts = mod.sanitize(text)
    assert "[EMAIL_001]" in out
    assert counts["EMAIL"] == 2
    assert len(mapping["EMAIL"]) == 1
    assert "[PHONE_INTL_001]" in out


def test_sanitize_span_types():
    text = "IBAN DE89370400440532013000 and URL https://example.com/path"
    out, _m, counts = mod.sanitize(text)
    assert "[IBAN_INTL_001]" in out
    assert "[URL_001]" in out
    assert counts["IBAN_INTL"] >= 1
    assert counts["URL"] >= 1


def test_sanitize_international_phone_variants():
    text = "US +1 (415) 555-2671 and UK +44 20 7946 0958"
    out, _m, counts = mod.sanitize(text)
    assert "[PHONE_INTL_001]" in out
    assert "[PHONE_INTL_002]" in out
    assert counts["PHONE_INTL"] == 2


def test_sanitize_reuses_existing_mapping():
    existing = {"EMAIL": {"a@b.com": "[EMAIL_007]"}}
    text = "a@b.com and c@d.com"
    out, mapping, counts = mod.sanitize(text, existing_mapping=existing)
    assert "[EMAIL_007]" in out
    assert "[EMAIL_008]" in out
    assert mapping["EMAIL"]["a@b.com"] == "[EMAIL_007]"
    assert mapping["EMAIL"]["c@d.com"] == "[EMAIL_008]"
    assert counts["EMAIL"] == 2


def test_default_mapping_path_is_canonical():
    assert str(mod.DEFAULT_MAPPING_PATH) == "sun/runtime/security-map.json"


def test_wrap_placeholders_for_markdown():
    text = "Contact [EMAIL_001] and [PHONE_INTL_003]."
    out = mod._wrap_placeholders_for_markdown(text)
    assert out == "Contact `[EMAIL_001]` and `[PHONE_INTL_003]`."
