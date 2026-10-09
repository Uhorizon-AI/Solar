# File-based lessons

## Propose, approve, persist

1. Identify a stable operational rule from verified evidence. Separate the rule
   from a one-off outcome. Do not duplicate CRM, accounting records, full
   conversations, identity data or secrets.
2. Check `planets/<planet>/agents/lecciones/<agent>/` for an equivalent rule.
   If updating one, show the current rule and the proposed replacement. After
   approval, overwrite the same lesson file and use the new approval date.
   The planet's Git history, when available, provides previous versions; do not
   embed an approval history or session log in the lesson.
3. Keep the pending proposal in the current conversation. Present its title,
   exact one-sentence rule and full destination path, and ask the responsible
   human to approve that text and its persistence. No pending file or queue is
   created by default. An explicit request to save a proposal needs a named
   destination; it must remain visibly unapproved and outside the approved
   lesson directory.
4. The agent handling the approval persists the exact approved rule using
   `assets/lesson.md` at
   `planets/<planet>/agents/lecciones/<agent>/<slug>.md`, dated with the human's
   local approval date. The approval
   must authorize saving at the stated destination, not merely agree with an
   idea. If approval arrives in a new conversation without the exact text and
   destination, recover that context or ask; never infer it.
5. Re-read the saved file and confirm its path and rule. If approval is denied,
   do not write or load the proposal as a rule. A conflicting lesson cannot
   override governance; ask to resolve or retire it before affected work.

## Usage examples

- A sales agent keeps a dated next step for every active opportunity. Load its
  canonical contract and applicable outreach lesson before drafting; a draft
  remains subject to its domain gate and human send approval.
- A product agent resumes prioritization. Load its contract and current product
  sources, then relevant lessons. A stale continuity record does not authorize
  changing priorities or repeating an earlier effect.
- A delivery agent repeatedly encounters missing evidence. Propose a precise
  evidence rule in the conversation; after explicit approval to save it, write
  it only in that agent's owning planet.
