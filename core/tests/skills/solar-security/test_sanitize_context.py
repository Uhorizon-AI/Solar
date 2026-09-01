from __future__ import annotations

import json
import sys
from pathlib import Path

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


def test_parse_extensions_arg_defaults():
    assert mod._parse_extensions_arg(None) == mod.DEFAULT_BATCH_EXTENSIONS


def test_parse_extensions_arg_custom():
    got = mod._parse_extensions_arg("MD,py")
    assert ".md" in got and ".py" in got


def test_iter_batch_files_respects_suffix_and_git(tmp_path: Path):
    root = tmp_path / "root"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "leak.md").write_text("# x", encoding="utf-8")
    good = root / "a.md"
    good.write_text("x", encoding="utf-8")
    skipped = root / "b.bin"
    skipped.write_bytes(b"\x00\x01")

    paths = mod._iter_batch_files(root.resolve(), frozenset({".md"}))
    assert paths == [good.resolve()]


def test_resolve_markdown_wrap_auto_md_path():
    assert (
        mod._resolve_markdown_wrap("auto", "-", (Path("/x/y/file.md"),)) is True
    )


def test_directory_mode_main_in_place(monkeypatch, tmp_path: Path):
    map_path = tmp_path / "security-map.json"
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "DEFAULT_MAPPING_PATH", map_path)

    doc = tmp_path / "batch"
    doc.mkdir()
    (doc / "first.md").write_text("alice@corp.test says hi\n", encoding="utf-8")
    (doc / "nested").mkdir()
    (doc / "nested" / "second.md").write_text("bob@corp.test too\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["sanitize_context.py", str(doc)])
    assert mod.main() == 0

    first = (doc / "first.md").read_text(encoding="utf-8")
    second = (doc / "nested" / "second.md").read_text(encoding="utf-8")
    assert "[EMAIL_001]" in first
    assert "[EMAIL_002]" in second
    persisted = json.loads(map_path.read_text(encoding="utf-8"))
    assert "EMAIL" in persisted


def test_directory_mode_rejects_second_output(monkeypatch, tmp_path: Path):
    map_path = tmp_path / "security-map.json"
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "DEFAULT_MAPPING_PATH", map_path)

    doc = tmp_path / "solo"
    doc.mkdir()

    monkeypatch.setattr(sys, "argv", ["sanitize_context.py", str(doc), "/tmp/out.md"])
    assert mod.main() == 2


def test_persist_preserves_custom_block(tmp_path: Path, monkeypatch):
    import io

    mapping_path = tmp_path / "security-map.json"
    mapping_path.write_text(
        json.dumps(
            {
                "CUSTOM": {"ACME Corp": "[COM]"},
                "EMAIL": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "DEFAULT_MAPPING_PATH", mapping_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("no emails here"))
    monkeypatch.setattr(sys, "argv", ["sanitize_context.py", "-"])
    assert mod.main() == 0

    data = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert data.get("CUSTOM") == {"ACME Corp": "[COM]"}
