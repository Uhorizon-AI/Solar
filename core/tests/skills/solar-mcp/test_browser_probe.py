"""The browser diagnostic accepts only its built-in fixture."""
from pathlib import Path
from subprocess import CompletedProcess, run

import operations
from mcp_helpers import execute


def test_browser_probe_reads_the_fixture_with_a_disposable_profile(solar_env, monkeypatch):
    def render(argv, **options):
        if "--dump-dom" not in argv:
            return run(argv, **options)
        profile = Path(next(arg.split("=", 1)[1] for arg in argv
                            if arg.startswith("--user-data-dir=")))
        assert profile.is_dir()
        assert "--headless" in argv
        assert "--dump-dom" in argv
        assert argv[-1].startswith("data:text/html,")
        assert options["timeout"] == 20
        profiles.append(profile)
        return CompletedProcess(argv, 0, "<main>solar-browser-42</main>", "")

    profiles = []
    which = operations.shutil.which
    monkeypatch.setattr(operations.shutil, "which",
                        lambda binary: "/fake/google-chrome" if binary == "google-chrome" else which(binary))
    monkeypatch.setattr(operations.subprocess, "run", render)
    body, error = execute("browser.probe", {}, approved=False)
    assert not error, body
    assert body["result"] == {"browser": "chrome", "headless": True, "fixture": "solar-browser-42"}
    assert len(profiles) == 1 and not profiles[0].exists()


def test_browser_probe_rejects_caller_control_before_launch(solar_env, monkeypatch):
    def unexpected_launch(*_args, **_kwargs):
        raise AssertionError("Chrome was launched for invalid input")

    monkeypatch.setitem(operations.HANDLERS, "browser.probe", unexpected_launch)
    for key in ("url", "profile", "script", "selector", "flags"):
        body, error = execute("browser.probe", {key: "outside-fixture"}, approved=False)
        assert error and body["code"] == "invalid_arguments", body
