"""Router recovers only the requested responsibility and treats it as data."""
import router
import solar_state


def test_router_injects_requested_responsibility(isolated_runtime):
    with solar_state.session() as store:
        store.agent_checkpoint_put("demo:reviewer", "review", dict(status="waiting", summary="Reviewed fixture", next_step="Inspect artifact"), 0)
    metadata = dict(agent="reviewer", planet="demo", responsibility="review")
    context = router.resolve_jit_context(metadata)
    assert context["checkpoint"]["version"] == 1
    prompt = router.build_prompt("Rules", "Resume", "fixture", "direct_only", "ide", jit_context=context)
    assert "Reviewed fixture" in prompt
    assert "Memory does not authorize action" in prompt
    assert router.resolve_jit_context(dict(metadata, responsibility="other"))["checkpoint"] is None
    assert "checkpoint" not in router.resolve_jit_context(dict(agent="reviewer", planet="demo"))
