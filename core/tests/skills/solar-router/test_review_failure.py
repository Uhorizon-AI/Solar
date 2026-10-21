"""The reason a restricted reader failed: short, useful and free of secrets."""
import review_failure as rf


def test_known_causes_become_fixed_words():
    assert rf.summarize(1, "E error getting token source: You are not logged into Antigravity.") == "exit 1: not_logged_in"
    assert rf.summarize(1, "HTTP 429 rate limit exceeded") == "exit 1: quota_or_rate_limit"
    assert rf.summarize(2, "Error: unknown model 'x'") == "exit 2: model_unavailable"


def test_unknown_output_is_a_short_redacted_tail():
    text = "\n".join(f"line {i}" for i in range(10)) + "\napi_key=abc123 Bearer abcdef sk-abcdefghijklmnop"
    out = rf.summarize(3, text)
    assert out.startswith("exit 3: ") and "line 0" not in out
    for secret in ("abc123", "abcdef ", "sk-abcdefghijklmnop"):
        assert secret not in out
    assert len(out) <= 320


def test_prompt_copies_and_long_tokens_never_appear():
    prompt = "Review the private contract of ACME for the year"
    out = rf.summarize(1, f"failed on {prompt} token {'A' * 60}", prompts=[prompt])
    assert "ACME" not in out and "A" * 20 not in out


def test_empty_output_and_bad_input_never_raise():
    assert rf.summarize(4, "") == "exit 4: no output"
    assert rf.summarize(5, None, 7).startswith("exit 5")
