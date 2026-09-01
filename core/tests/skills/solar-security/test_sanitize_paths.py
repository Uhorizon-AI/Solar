from __future__ import annotations

from pathlib import Path

import sanitize_paths as mod


def test_dry_run_does_not_modify_files(tmp_path: Path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    old_file = docs_dir / "report_TOKEN_SOURCE_v1.md"
    old_file.write_text("# content\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.md"
    pipeline.write_text(
        "[link](docs/report_TOKEN_SOURCE_v1.md)\n",
        encoding="utf-8",
    )

    renamed, updated_docs = mod.run(
        target=tmp_path,
        old="TOKEN_SOURCE",
        new="TOKEN_TARGET",
        dry_run=True,
        use_mapping=False,
    )

    assert renamed == 1
    assert updated_docs == 1
    assert old_file.exists()
    assert "TOKEN_SOURCE" in pipeline.read_text(encoding="utf-8")


def test_apply_renames_and_updates_references(tmp_path: Path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    old_file = docs_dir / "report_TOKEN_SOURCE_v1.md"
    old_file.write_text("# content\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.md"
    pipeline.write_text(
        "[link](docs/report_TOKEN_SOURCE_v1.md)\n",
        encoding="utf-8",
    )

    renamed, updated_docs = mod.run(
        target=tmp_path,
        old="TOKEN_SOURCE",
        new="TOKEN_TARGET",
        dry_run=False,
        use_mapping=False,
    )

    new_file = docs_dir / "report_TOKEN_TARGET_v1.md"
    assert renamed == 1
    assert updated_docs == 1
    assert not old_file.exists()
    assert new_file.exists()
    assert "report_TOKEN_TARGET_v1.md" in pipeline.read_text(encoding="utf-8")


def test_mapping_rules_are_used_for_renames(tmp_path: Path):
    mapping = tmp_path / "security-map.json"
    mapping.write_text('{"CUSTOM":{"TOKEN_SOURCE":"TOKEN_TARGET"}}', encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    old_file = docs_dir / "x_TOKEN_SOURCE.md"
    old_file.write_text("# x\n", encoding="utf-8")
    md = tmp_path / "index.md"
    md.write_text("[x](docs/x_TOKEN_SOURCE.md)\n", encoding="utf-8")

    renamed, updated_docs = mod.run(
        target=tmp_path,
        dry_run=False,
        mapping_path=mapping,
        use_mapping=True,
    )

    assert renamed == 1
    assert updated_docs == 1
    assert not old_file.exists()
    assert (docs_dir / "x_TOKEN_TARGET.md").exists()
    assert "x_TOKEN_TARGET.md" in md.read_text(encoding="utf-8")


def test_use_mapping_without_mapping_path_uses_default_file(monkeypatch, tmp_path: Path):
    """When mapping_path is None, rules load from DEFAULT_MAPPING_PATH (same contract as sanitize_context)."""
    mapping = tmp_path / "security-map.json"
    mapping.write_text('{"CUSTOM":{"TOKEN_SOURCE":"TOKEN_TARGET"}}', encoding="utf-8")
    monkeypatch.setattr(mod, "DEFAULT_MAPPING_PATH", mapping)

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    old_file = docs_dir / "note_TOKEN_SOURCE.md"
    old_file.write_text("# n\n", encoding="utf-8")

    renamed, updated_docs = mod.run(
        target=tmp_path,
        dry_run=True,
        mapping_path=None,
        use_mapping=True,
    )

    assert renamed == 1
    assert updated_docs == 0
    assert old_file.exists()
