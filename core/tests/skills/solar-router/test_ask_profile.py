"""The ask_readonly_v1 profile: a canonical manifest, verified again before launch, run through
BaseProvider.ask with the client's own session. Providers are mocked; no AI binary runs."""
import pytest
from unittest.mock import MagicMock, patch

import execution_profiles as ep
from providers import PROVIDERS


def test_the_envelope_is_canonical_and_verifiable(tmp_path):
    built = ep.build_ask_envelope(provider="codex", prompt="Hi?\r\n", cwd=str(tmp_path), model=None)
    manifest = built["manifest"]
    assert manifest["execution_profile"] == "ask_readonly_v1"
    assert manifest["composition"] == "ask_envelope_v1"
    again = ep.verify_envelope(manifest, built["review_input_digest"], provider="codex", profile="ask_readonly_v1")
    assert again == manifest
    assert ep.ask_prompt(manifest) == "Hi?\n"


@pytest.mark.parametrize("change", ["prompt", "provider", "model", "cwd"])
def test_a_changed_manifest_is_rejected(tmp_path, change):
    built = ep.build_ask_envelope(provider="codex", prompt="Hi", cwd=str(tmp_path), model=None)
    manifest = dict(built["manifest"])
    provider = "codex"
    if change == "prompt":
        manifest["user_prompt"] = manifest["user_prompt"].replace("Hi", "Ho")
    elif change == "provider":
        provider = "claude"
    elif change == "model":
        manifest["model"] = "other"
    else:
        manifest["user_prompt"] = manifest["user_prompt"].replace(str(tmp_path), "/etc")
    with pytest.raises(ep.ProfileError):
        ep.verify_envelope(manifest, built["review_input_digest"], provider=provider, profile="ask_readonly_v1")


@pytest.mark.parametrize("kwargs", [dict(prompt=""), dict(prompt="  "), dict(cwd="relative"),
                                    dict(model="-x"), dict(provider="ollama")])
def test_invalid_input_is_refused(tmp_path, kwargs):
    base = dict(provider="codex", prompt="Hi", cwd=str(tmp_path), model=None)
    with pytest.raises(ep.ProfileError):
        ep.build_ask_envelope(**dict(base, **kwargs))


def test_too_large_a_prompt_is_refused(tmp_path):
    with pytest.raises(ep.ProfileError) as ctx:
        ep.build_ask_envelope(provider="codex", prompt="x" * (ep.MAX_INPUT_BYTES + 1), cwd=None, model=None)
    assert ctx.value.code == "review_input_too_large"


def test_the_folder_must_still_exist_before_launch(tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    built = ep.build_ask_envelope(provider="codex", prompt="Hi", cwd=str(folder), model=None)
    folder.rmdir()
    with pytest.raises(ep.ProfileError):
        ep.verify_sources(built["manifest"], [str(folder)])


def _proc(stdout="the answer", returncode=0, stderr=""):
    proc = MagicMock()
    proc.returncode, proc.stdout, proc.stderr = returncode, stdout, stderr
    return proc


@pytest.mark.parametrize("provider", ["claude", "codex", "agent", "agy"])
def test_run_review_asks_with_the_clients_own_session(tmp_path, provider):
    built = ep.build_ask_envelope(provider=provider, prompt="Hi", cwd=str(tmp_path), model="m-1")
    adapter = PROVIDERS[provider]
    adapter.last_review_preflight = {}
    with patch("providers.base.shutil.which", side_effect=lambda b, path=None: f"/bin/{b}"), \
         patch("providers.base.subprocess.run", return_value=_proc()) as run:
        text = adapter.run("", review=dict(manifest=built["manifest"], expected=built["review_input_digest"],
                                           profile="ask_readonly_v1", before_launch=lambda: None))
    assert text == "the answer"
    assert str(run.call_args.kwargs["cwd"]) == str(tmp_path)
    assert "--model" in run.call_args.args[0]
    assert adapter.last_review_preflight["read_only_mode"]


def test_before_launch_runs_and_can_stop_the_launch(tmp_path):
    built = ep.build_ask_envelope(provider="codex", prompt="Hi", cwd=None, model=None)

    def refuse():
        raise ep.ProfileError("review_input_mismatch")

    with patch("providers.base.subprocess.run") as run:
        with pytest.raises(ep.ProfileError):
            PROVIDERS["codex"].run("", review=dict(manifest=built["manifest"], expected=built["review_input_digest"],
                                                   profile="ask_readonly_v1", before_launch=refuse))
    run.assert_not_called()


def test_a_failure_names_the_reason(tmp_path):
    built = ep.build_ask_envelope(provider="agent", prompt="Hi", cwd=None, model=None)
    with patch("providers.base.shutil.which", return_value="/bin/agent"), \
         patch("providers.base.subprocess.run",
               return_value=_proc(stdout="", returncode=1, stderr="Error: not logged in")):
        with pytest.raises(RuntimeError) as ctx:
            PROVIDERS["agent"].run("", review=dict(manifest=built["manifest"],
                                                   expected=built["review_input_digest"],
                                                   profile="ask_readonly_v1", before_launch=lambda: None))
    assert "not_logged_in" in str(ctx.value)
