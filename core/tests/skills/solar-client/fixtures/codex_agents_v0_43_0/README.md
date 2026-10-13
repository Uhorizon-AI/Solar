# Real output of Solar v0.43.0

`published/` holds the files that `codex_agents.py` from tag `v0.43.0` wrote for the
synthetic contracts in `contracts/` (`published/solar-managed.json` is the
`.codex/agents/.solar-managed.json` it wrote, without the leading dot). Nothing was
rewritten by hand. Regenerate with:

```bash
git show v0.43.0:core/skills/solar-client/scripts/codex_agents.py > old.py
# workspace with .solar/settings.json and planets/<planet>/agents/<agent>.md from contracts/
python3 old.py --workspace <ws> enable && python3 old.py --workspace <ws> publish
```

`test_codex_agents.py` migrates this state with the current publisher.
