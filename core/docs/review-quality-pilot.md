# Review quality pilot (prepared, not executed)

This protocol compares a live-reference review with `text_only_review_v1` on
three known cases using **the same exact Claude model and rubric**. Preparation,
source validation and result aggregation are offline. The runner never invokes
a provider, reads credentials or authorizes spending. Automated doubles and
fixture validation are not real pilot results.

## Prepare and authorize

Choose a new local evidence directory outside the repository and runtime. Run:

```sh
python3 core/tests/support/review_quality_pilot.py prepare \
  --directory /private/tmp/solar-quality-pilot-UNIQUE --model EXACT_MODEL_ID
```

This creates `pilot.json`, a `results.json` template, sources and the canonical
approved-envelope inputs for each case. The directory must not already exist.
Do not publish the account reference or captured review outputs with secrets.

Before any real inference, Louis must approve the named account, exact model,
both arms, maximum six attempts (five inference calls and one expected refusal),
maximum aggregate dollar cost and elapsed-time budget. Record that approval's
reference, operator, nonsecret account reference, timestamp and `max_cost_usd`
in `results.json.authorization`; these are evidence fields, not an approval gate
or a way to grant authority. Use the normal Solar task approval/reservation
workflow for each restricted launch. No standalone provider CLI bypass is part
of this runner. Further attempts require authority within the original cap or
a new approval. Keep the production reader profile disabled during the pilot.

## Cases and paired execution

| Case | Ground truth | Required result |
|---|---|---|
| `contradiction` | Requirements say batch maximum three; operations say five | Both arms identify and cite both limits, without guessing precedence |
| `omitted-datum` | Measurement is 120 ms; required target is absent | Both arms report insufficient information rather than inventing a target |
| `changed-source` | Retry limit changes from two to four after capture | Package preflight returns `review_input_mismatch` before inference; live reference sees four |

The runner deliberately mutates only the changed-source fixture **after**
capturing its envelope. All fixtures are synthetic. Supply identical instructions
and rules from `pilot.json` to both arms. The live reference may read the fixture
files; restrict its scope to that case directory. The package arm receives the
exact canonical envelope via the existing approved restricted task path. Record
the approved task IDs, digest, CLI version and effective policy diagnosis in
notes. Record the real pre-launch refusal for changed-source, not just the
runner's offline `offline_preflight` observation. Do not edit a captured envelope
to make a failed freshness check pass: prepare and approve a new one.

Record source hashes and observation times immediately before each arm and after
completion. A post-capture change blocks package launch; a change after launch
invalidates that result for approving the new source version. A stale package's
text must never count as a live verification. A reference arm does not receive
the expected-answer field during inference; the evaluator uses it afterwards.

## Shared rubric: `review-quality-v1`

Score each arm independently before comparing it. Use the same evaluator and
preserve exact raw output (or refusal) under the pilot directory.

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Detection | Misses or reverses expected issue | Mentions issue incompletely | Identifies full contradiction/missing target, or refuses stale package |
| Evidence | Unsupported claims or invented facts | Partial references | Correct source references and explicit uncertainty; refusal identifies the mismatch |
| Freshness | Claims unverified live freshness | Qualifies capture but lacks validation | Source validation documented; stale input refused before inference |

Count omissions against each case's expected result and false positives as
unsupported additional findings. Record `started_at`/`finished_at` in ISO 8601
with timezone, wall time, actual input/output token usage, actual USD cost,
source freshness and an output-file path relative to the pilot directory. Use
zero inference tokens/cost for the expected refusal; do not turn unknown billed
usage into zero. Missing measurements keep the pilot incomplete. Explain any
model/provider refusal, extra overhead, uncertain billing or invalidated result.

Fill all six entries in `results.json`, replacing `not_run` with `completed` or
`rejected_before_launch` for the changed-source package. Set `source_freshness`
to `current` or `review_input_mismatch` for that expected refusal. Preserve
captured digests. Aggregate without running inference:

```sh
python3 core/tests/support/review_quality_pilot.py report \
  --directory /private/tmp/solar-quality-pilot-UNIQUE
```

The runner refuses incomplete/mismatched pairs and outputs measurements, budget
status and a strict quality gate: scores all 2, zero omissions and zero false
positives. Operator review must confirm source-hash evidence and authorization;
self-reported fields cannot establish either. A passing report never authorizes
rollout. On failure keep the profile as text evaluation, do not use it to close
a repository review, and keep concurrent useful reviews disabled. Follow the
separate [rollout prerequisites](async-rollout.md).
