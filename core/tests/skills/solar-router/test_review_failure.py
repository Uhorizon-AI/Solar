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


def test_quoted_secret_keys_are_redacted():
    from review_failure import redact
    for text in ('{"api_key": "demo-sensitive-value"}', "{'password': 'demo-password'}",
                 'token="abc"', "secret = 'x1'"):
        out = redact(text)
        for leaked in ("demo-sensitive-value", "demo-password", "abc", "x1"):
            assert leaked not in out, (text, out)


def test_escaped_quotes_inside_a_secret_do_not_leak_the_tail():
    from review_failure import redact
    for text in ('{"password":"prefix\\"private-tail"}', "{'token': 'a\\'private-tail'}"):
        assert "private-tail" not in redact(text), text


def test_authorization_headers_hide_the_whole_credential_not_only_the_scheme():
    """PR 145 review: `Authorization: Basic <credential>` used to leave the credential in the error."""
    for header in ("Authorization", "Proxy-Authorization", "authorization"):
        for scheme in ("Basic", "Bearer", "Token", "Digest"):
            out = rf.summarize(0, f"warming up\n{header}: {scheme} dGVzdDpmaWN0aXRpb3Vz\nended")
            assert "dGVzdDpmaWN0aXRpb3Vz" not in out, (header, scheme, out)
            assert "ended" in out
    assert "dGVzdDpmaWN0aXRpb3Vz" not in rf.summarize(1, "Authorization=Basic dGVzdDpmaWN0aXRpb3Vz")
    assert "dGVzdDpmaWN0aXRpb3Vz" not in rf.summarize(1, '{"Authorization": "Basic dGVzdDpmaWN0aXRpb3Vz"}')


def test_digest_parameters_and_a_following_secret_on_the_same_line_are_hidden():
    """PR 145 review: the value used to stop at the first comma."""
    out = rf.summarize(0, 'boot\nAuthorization: Digest username="alice", realm="x", nonce="n0nc3x", '
                          'response="supersecretresponse"\nnext line is the diagnosis')
    for leaked in ("supersecretresponse", "n0nc3x", "alice"):
        assert leaked not in out, out
    assert "next line is the diagnosis" in out
    out = rf.summarize(0, "Authorization: Basic dGVzdA==, token=abc999secret\nafter")
    assert "abc999secret" not in out and "dGVzdA" not in out and "after" in out
    assert "supersecretresponse" not in rf.summarize(1, "Proxy-Authorization: Digest a=\"1\", response=\"supersecretresponse\"")


def test_prose_after_an_authorization_name_keeps_its_cause_but_parameter_schemes_are_hidden():
    """PR 145 review: `authorization: denied because ...` is a diagnosis, not a credential."""
    out = rf.summarize(0, "authorization: denied because the sandbox blocked the command")
    assert "sandbox blocked the command" in out
    for line in ('Authorization: Hawk id="abc", ts="1", mac="supermac"',
                 "Authorization: AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261106/x, Signature=supersig"):
        out = rf.summarize(0, line + "\nafter")
        assert "supermac" not in out and "supersig" not in out and "AKIDEXAMPLE" not in out, out
        assert "after" in out


def test_any_authorization_scheme_is_hidden_to_the_end_of_the_line():
    """PR 145 review: a list of known schemes failed open for DPoP, Zoho-oauthtoken, ApiKey, SSWS or Bot."""
    for scheme, secret in (("DPoP", "fictitious~token.456"), ("Zoho-oauthtoken", "1000.abc123def"),
                           ("ApiKey", "abc123def"), ("SSWS", "abc123def"), ("Bot", "abc123def")):
        for header in ("Authorization", "Proxy-Authorization"):
            out = rf.summarize(0, f"{header}: {scheme} {secret}\nafter the header")
            assert secret not in out, (scheme, out)
            assert "after the header" in out, (scheme, out)
