"""Client-side dashboard registration: settings only, atomic, never a tool start.

Every test builds a temporary workspace. Nothing here touches a real Solar
workspace, a real planet file or a real tool.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3]
SCRIPTS = CORE / "skills/solar-client/scripts"
SCRIPT = SCRIPTS / "dashboards.py"


def write_settings(ws, **extra):
    data = {"core_source": "global", "layout": "solar-client-v1.2", "scope": "workspace"}
    data.update(extra)
    (ws / ".solar").mkdir(exist_ok=True)
    (ws / ".solar/settings.json").write_text(json.dumps(data, indent=2) + "\n")


def settings(ws):
    return json.loads((ws / ".solar/settings.json").read_text())


def run(ws, *args, env=None):
    full = dict(os.environ if env is None else env)
    full.setdefault("PATH", os.environ.get("PATH", ""))
    return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws), *args],
                          capture_output=True, text=True, env=full, timeout=60)


def test_register_writes_only_settings_and_preserves_other_keys(tmp_path):
    write_settings(tmp_path, custom_user="keep-me", sync_exclude_planets=["solar"])
    result = run(tmp_path, "register", "uhorizon:triage", "--start-command", "python3 server.py 8777")
    assert result.returncode == 0, result.stderr
    data = settings(tmp_path)
    assert data["custom_user"] == "keep-me"
    assert data["sync_exclude_planets"] == ["solar"]
    assert data["layout"] == "solar-client-v1.2"
    assert data["dashboards"] == {
        "enabled": True,
        "registered": [{"id": "uhorizon:triage", "start_command": "python3 server.py 8777"}],
    }


def test_register_never_reads_or_writes_a_planet_file(tmp_path):
    write_settings(tmp_path)
    planet = tmp_path / "planets/uhorizon/.solar"
    planet.mkdir(parents=True)
    declaration = planet / "dashboards.json"
    declaration.write_text('{"version":1,"dashboards":[]}')
    before = declaration.read_bytes()
    result = run(tmp_path, "register", "uhorizon:triage")
    assert result.returncode == 0, result.stderr
    assert declaration.read_bytes() == before
    assert settings(tmp_path)["dashboards"]["registered"] == [
        {"id": "uhorizon:triage", "start_command": None}]


def test_register_is_idempotent_and_updates_the_command(tmp_path):
    write_settings(tmp_path)
    assert run(tmp_path, "register", "uhorizon:triage").returncode == 0
    assert run(tmp_path, "register", "uhorizon:triage").returncode == 0
    assert len(settings(tmp_path)["dashboards"]["registered"]) == 1
    assert run(tmp_path, "register", "uhorizon:triage", "--start-command", "run.sh").returncode == 0
    rows = settings(tmp_path)["dashboards"]["registered"]
    assert rows == [{"id": "uhorizon:triage", "start_command": "run.sh"}]


def test_unregister_and_absent_target_are_ok(tmp_path):
    write_settings(tmp_path)
    run(tmp_path, "register", "uhorizon:triage")
    result = run(tmp_path, "unregister", "uhorizon:triage")
    assert result.returncode == 0, result.stderr
    assert settings(tmp_path)["dashboards"]["registered"] == []
    assert run(tmp_path, "unregister", "uhorizon:triage").returncode == 0


def test_enable_disable_keep_the_registration(tmp_path):
    write_settings(tmp_path)
    run(tmp_path, "register", "uhorizon:triage", "--start-command", "run.sh")
    assert run(tmp_path, "disable").returncode == 0
    data = settings(tmp_path)
    assert data["dashboards"]["enabled"] is False
    assert len(data["dashboards"]["registered"]) == 1
    assert run(tmp_path, "enable").returncode == 0
    assert settings(tmp_path)["dashboards"]["enabled"] is True


def test_status_and_list_report_both_forms(tmp_path):
    write_settings(tmp_path)
    run(tmp_path, "register", "uhorizon:triage", "--start-command", "run.sh")
    listed = run(tmp_path, "list", "--json")
    assert listed.returncode == 0
    assert json.loads(listed.stdout)["registered"] == [
        {"id": "uhorizon:triage", "start_command": "run.sh"}]
    status = run(tmp_path, "status")
    assert status.returncode == 0
    assert "registered: 1" in status.stdout


def test_invalid_targets_are_refused(tmp_path):
    write_settings(tmp_path)
    for target in ("triage", "uhorizon:", ":triage", "uhorizon:triage:extra", "uh orizon:x"):
        result = run(tmp_path, "register", target)
        assert result.returncode == 2, target
    assert "dashboards" not in settings(tmp_path)


def test_invalid_settings_are_refused_without_writing(tmp_path):
    (tmp_path / ".solar").mkdir()
    raw = '{"layout":"solar-client-v1.2","dashboards":{"unknown":1}}'
    (tmp_path / ".solar/settings.json").write_text(raw)
    result = run(tmp_path, "register", "uhorizon:triage")
    assert result.returncode == 2
    assert (tmp_path / ".solar/settings.json").read_text() == raw


def test_corrupt_settings_are_refused(tmp_path):
    (tmp_path / ".solar").mkdir()
    (tmp_path / ".solar/settings.json").write_text("{not json")
    result = run(tmp_path, "register", "uhorizon:triage")
    assert result.returncode == 2
    assert "{not json" in (tmp_path / ".solar/settings.json").read_text()


def test_legacy_manifest_is_read_and_migrated_to_settings(tmp_path):
    (tmp_path / ".solar").mkdir()
    (tmp_path / ".solar/manifest.json").write_text(json.dumps({"custom_user": "keep-me"}))
    assert run(tmp_path, "register", "uhorizon:triage").returncode == 0
    assert not (tmp_path / ".solar/manifest.json").exists()
    assert settings(tmp_path)["custom_user"] == "keep-me"


def test_start_command_must_be_bounded_and_not_empty(tmp_path):
    write_settings(tmp_path)
    assert run(tmp_path, "register", "uhorizon:triage", "--start-command", "").returncode == 2
    assert run(tmp_path, "register", "uhorizon:triage", "--start-command", "x" * 4001).returncode == 2
    assert "dashboards" not in settings(tmp_path)


def test_duplicate_and_unknown_entries_in_settings_are_refused(tmp_path):
    write_settings(tmp_path, dashboards={
        "enabled": True,
        "registered": [{"id": "a:b"}, {"id": "a:b"}],
    })
    assert run(tmp_path, "status").returncode == 2
    write_settings(tmp_path, dashboards={"registered": [{"id": "a:b", "extra": 1}]})
    assert run(tmp_path, "status").returncode == 2


def declaration_path(ws, planet="uhorizon"):
    return ws / "planets" / planet / ".solar/dashboards.json"


def make_planet(ws, planet="uhorizon"):
    (ws / "planets" / planet).mkdir(parents=True)


def test_seed_creates_the_declaration_when_absent(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    result = run(tmp_path, "seed", "uhorizon")
    assert result.returncode == 0, result.stderr
    data = json.loads(declaration_path(tmp_path).read_text())
    assert data["version"] == 1
    assert [row["name"] for row in data["dashboards"]] == ["example-tool", "example-view"]
    assert "url" in data["dashboards"][0] and "file" in data["dashboards"][1]
    assert "register uhorizon:<name>" in result.stdout


def test_seed_validates_an_existing_declaration_without_writing(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    target = declaration_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"version": 1, "dashboards": []}))
    before = target.read_bytes()
    result = run(tmp_path, "seed", "uhorizon")
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == before
    assert "nothing was changed" in result.stdout


def test_a_fresh_seed_template_is_a_placeholder_until_filled(tmp_path):
    # The template carries empty metadata on purpose: the console must not list a
    # bogus surface, so a second `seed` reports the missing fields instead of
    # blessing the file.
    write_settings(tmp_path)
    make_planet(tmp_path)
    assert run(tmp_path, "seed", "uhorizon").returncode == 0
    again = run(tmp_path, "seed", "uhorizon")
    assert again.returncode == 2
    assert "title must be a non-empty bounded string" in again.stderr


def declaration(tmp_path, entry):
    target = declaration_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"version": 1, "dashboards": [entry]}))
    return target


def test_an_entry_declares_exactly_one_of_url_or_file(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    base = {"name": "x", "title": "T", "description": "D", "owner": "O",
            "updated_at": "2026-10-13", "mode": "read_only"}
    # Both and neither are refused, and the file is left untouched.
    for entry in (dict(base, url="http://127.0.0.1:1/", file="operations/a.html"),
                  dict(base)):
        target = declaration(tmp_path, entry)
        before = target.read_bytes()
        result = run(tmp_path, "seed", "uhorizon")
        assert result.returncode == 2, entry
        assert "exactly one of url or file" in result.stderr
        assert target.read_bytes() == before
    # A valid file entry is accepted (the declaration is validated, not rewritten).
    declaration(tmp_path, dict(base, file="operations/leadership/reports/daily.html"))
    assert run(tmp_path, "seed", "uhorizon").returncode == 0
    # A file outside operations/ or without a .html suffix is refused.
    for bad in ("private/notes.html", "/etc/notes.html", "operations/notes.txt",
                "../outside.html", "operations/../escape.html"):
        declaration(tmp_path, dict(base, file=bad))
        result = run(tmp_path, "seed", "uhorizon")
        assert result.returncode == 2, bad
        assert "file must be an HTML page inside operations/" in result.stderr


def test_seed_refuses_an_invalid_declaration_without_overwriting(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    target = declaration_path(tmp_path)
    target.parent.mkdir(parents=True)
    raw = '{"version": 1, "dashboards": [{"name": "x"}]}'
    target.write_text(raw)
    result = run(tmp_path, "seed", "uhorizon")
    assert result.returncode == 2
    assert target.read_text() == raw


def test_seed_force_overwrites_with_the_template(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    target = declaration_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text('{"version": 1, "dashboards": []}')
    result = run(tmp_path, "seed", "uhorizon", "--force")
    assert result.returncode == 0, result.stderr
    assert "overwrote" in result.stdout
    assert json.loads(target.read_text())["dashboards"][0]["name"] == "example-tool"
    backup = target.with_name(target.name + ".bak")
    assert backup.exists()
    assert json.loads(backup.read_text())["dashboards"] == []


def test_seed_force_never_follows_a_planted_backup_symlink(tmp_path):
    # A symlink left at `dashboards.json.bak` must never become the write target:
    # the backup is created exclusively, so the link is skipped and its
    # destination outside the planet is left untouched.
    write_settings(tmp_path)
    make_planet(tmp_path)
    target = declaration_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text('{"version": 1, "dashboards": []}')
    outside = tmp_path / "outside.json"
    outside.write_text("SECRET")
    target.with_name(target.name + ".bak").symlink_to(outside)
    result = run(tmp_path, "seed", "uhorizon", "--force")
    assert result.returncode == 0, result.stderr
    assert outside.read_text() == "SECRET"
    followup = target.with_name(target.name + ".bak.2")
    assert followup.exists()
    assert json.loads(followup.read_text())["dashboards"] == []


def test_seed_force_adds_a_backup_and_keeps_the_earlier_one(tmp_path):
    # Repeated --force never replaces an existing backup; it adds the next one.
    write_settings(tmp_path)
    make_planet(tmp_path)
    target = declaration_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text('{"version": 1, "dashboards": []}')
    assert run(tmp_path, "seed", "uhorizon", "--force").returncode == 0
    first = target.with_name(target.name + ".bak")
    first_content = first.read_bytes()
    target.write_text('{"version": 1, "dashboards": [{"name": "only"}]}')
    assert run(tmp_path, "seed", "uhorizon", "--force").returncode == 0
    assert first.read_bytes() == first_content
    second = target.with_name(target.name + ".bak.2")
    assert second.exists()
    assert json.loads(second.read_text())["dashboards"] == [{"name": "only"}]


def test_register_keeps_the_existing_scope_and_layout(tmp_path):
    # `register` must never rewrite scope/layout: they are owned by client_lib.sh
    # and codex_agents.py, and a silent change here would be invisible.
    write_settings(tmp_path, layout="solar-client-v9.9", scope="planet")
    result = run(tmp_path, "register", "uhorizon:triage")
    assert result.returncode == 0, result.stderr
    data = settings(tmp_path)
    assert data["layout"] == "solar-client-v9.9"
    assert data["scope"] == "planet"


def test_seed_says_the_template_entries_are_invalid_until_filled(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    result = run(tmp_path, "seed", "uhorizon")
    assert result.returncode == 0, result.stderr
    assert "valid until filled" in result.stdout or "invalid until filled" in result.stdout


def test_a_url_port_with_a_leading_zero_is_refused(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    base = {"name": "x", "title": "T", "description": "D", "owner": "O",
            "updated_at": "2026-10-13", "mode": "read_only"}
    for url in ("http://127.0.0.1:080/", "http://localhost:00/", "http://127.0.0.1:00080/"):
        declaration(tmp_path, dict(base, url=url))
        result = run(tmp_path, "seed", "uhorizon")
        assert result.returncode == 2, url
        assert "url must be a loopback HTTP root" in result.stderr


def test_a_view_must_be_read_only(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    declaration(tmp_path, {"name": "v", "title": "T", "description": "D", "owner": "O",
                           "updated_at": "2026-10-13", "mode": "interactive",
                           "file": "operations/leadership/reports/daily.html"})
    result = run(tmp_path, "seed", "uhorizon")
    assert result.returncode == 2
    assert "a file view is always read_only" in result.stderr


def test_seed_refuses_a_symlinked_solar_directory(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "planets/uhorizon/.solar").symlink_to(outside)
    result = run(tmp_path, "seed", "uhorizon")
    assert result.returncode == 5
    assert not (outside / "dashboards.json").exists()


def test_seed_refuses_a_symlinked_declaration(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    target = declaration_path(tmp_path)
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text('{"version": 1, "dashboards": []}')
    target.symlink_to(outside)
    result = run(tmp_path, "seed", "uhorizon")
    assert result.returncode == 5
    assert outside.read_text() == '{"version": 1, "dashboards": []}'


def test_seed_rejects_invalid_planet_names_and_missing_planets(tmp_path):
    write_settings(tmp_path)
    make_planet(tmp_path)
    for planet in ("..", ".", "with space", "a/b", ""):
        assert run(tmp_path, "seed", planet).returncode == 2, planet
    assert run(tmp_path, "seed", "ghost").returncode == 2
    assert not declaration_path(tmp_path, "ghost").exists()
