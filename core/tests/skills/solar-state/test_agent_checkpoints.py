"""Responsibility isolation, stale-write protection and lossless rollback refusal."""
import pytest
import solar_state as st
import solar_state_cutover as cut

DATA = dict(status="waiting", summary="Reviewed fixture", next_step="Inspect artifact", artifact_refs=["artifact.md"])


def test_checkpoint_survives_sessions_and_isolates_keys(ready):
    with st.session(ready) as store:
        assert store.agent_checkpoint_get("demo:analyst", "review") is None
        saved = store.agent_checkpoint_put("demo:analyst", "review", DATA, 0)
        assert saved["version"] == 1
        store.agent_checkpoint_put("demo:analyst", "delivery", DATA, 0)
        with pytest.raises(st.StateError, match="conflict"):
            store.agent_checkpoint_put("demo:analyst", "review", DATA, 0)
    with st.read_session(ready) as store:
        assert store.agent_checkpoint_get("demo:analyst", "review")["data"] == DATA
        assert store.agent_checkpoint_get("other:analyst", "review") is None
        assert store.agent_checkpoint_count() == 2


@pytest.mark.parametrize("agent,responsibility,data,version", [
    ("../outside", "review", DATA, 0), ("demo", "review", DATA, True),
    ("demo", "review", dict(DATA, summary="x" * 2001), 0),
    ("demo", "review", dict(DATA, authority="A3"), 0),
    ("demo", "review", dict(DATA, artifact_refs=["x"] * 21), 0),
])
def test_checkpoint_rejects_unbounded_or_authority_fields(ready, agent, responsibility, data, version):
    with st.session(ready) as store:
        with pytest.raises(st.StateError):
            store.agent_checkpoint_put(agent, responsibility, data, version)
        assert store.agent_checkpoint_count() == 0


def test_rollback_refuses_before_removing_staging(ready, monkeypatch):
    monkeypatch.setenv(cut.ALLOW_ENV, "1")
    with st.session(ready) as store:
        store.agent_checkpoint_put("demo", "review", DATA, 0)
    staging = ready / cut.ROLLBACK_STAGING
    staging.mkdir()
    sentinel = staging / "keep"
    sentinel.write_text("not exported")
    with pytest.raises(cut.CutoverRefused, match="checkpoints"):
        cut.rollback(ready, lister=lambda: [])
    assert sentinel.read_text() == "not exported"
    assert st.read_format(ready) == st.FORMAT_SQLITE
