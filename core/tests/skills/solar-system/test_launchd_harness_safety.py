"""Offline guards and failure cleanup of the opt-in real launchd harness."""
import os
from pathlib import Path

import pytest
import test_launchd_evidence as evidence
from dead_process import dead_pid


@pytest.mark.parametrize("attribute,value", [
    ("label", "com.solar.system"),
    ("runtime", evidence.LIVE_RUNTIME / "runtime"),
    ("install", Path.home() / ".local/share/solar"),
    ("workspace", Path.home() / "Solar"),
])
def test_real_launchd_harness_refuses_unsafe_destinations(attribute, value):
    rig = evidence.LaunchdRig()
    setattr(rig, attribute, value)
    with pytest.raises(ValueError, match="refused"):
        rig.assert_safe()


@pytest.mark.parametrize("key,value", [
    ("SOLAR_ROOT", str(Path.home() / ".local/share/solar")),
    ("SOLAR_APP_TEST_PORT", "9000"),
])
def test_real_launchd_harness_refuses_unsafe_environment(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="refused"):
        evidence.LaunchdRig().assert_safe()


def test_identity_signal_requires_both_pid_and_start(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "kill", lambda *args: calls.append(args))
    assert not evidence._kill_by_identity(dead_pid(), None)
    assert not calls


def test_fixture_cleans_up_even_when_bootstrap_fails(monkeypatch):
    calls = []

    class FailedRig:
        def setup(self):
            calls.append("setup")
        def install_agent(self):
            raise RuntimeError("bootstrap failed")
        def cleanup(self):
            calls.append("cleanup")

    monkeypatch.setattr(evidence.sys, "platform", "darwin")
    monkeypatch.setenv("SOLAR_TEST_LAUNCHD", "1")
    monkeypatch.setattr(evidence, "_launchctl", lambda: __file__)
    monkeypatch.setattr(evidence, "LaunchdRig", FailedRig)
    generator = evidence.rig.__wrapped__()
    with pytest.raises(RuntimeError, match="bootstrap failed"):
        next(generator)
    assert calls == ["setup", "cleanup"]


def test_refused_setup_cannot_bootout_a_production_label_during_cleanup(monkeypatch):
    rig = evidence.LaunchdRig()
    rig.label = "com.solar.system"
    def unexpected_call(*args):
        raise AssertionError("cleanup reached launchctl for a refused label")
    monkeypatch.setattr(evidence, "_plist_label_listed", unexpected_call)
    with pytest.raises(ValueError, match="refused"):
        rig.cleanup()
