# Complete console task detail

Date: 2026-10-12
Status: pending_review

## Objective

Read and display a complete SQLite task record through solar-state, including all columns, frontmatter and Markdown instructions, while preserving execution history and approvals.

## Scope

Console-only full-record read endpoint and generic HTML presentation. No manually curated context/schedule projection, task export to Markdown, shared checkpoint parser, MCP changes or solar-state changes. Existing console task-list APIs provide summaries only, so the detail endpoint remains necessary.

The body alone is rendered with a conservative dependency-free Markdown renderer and then sanitized using an HTML allowlist. Unsupported syntax stays text; raw HTML and images are inert. Per-field display preserves unknown/new fields and malformed metadata. Corrupt frontmatter JSON falls back to the raw complete row within the same solar-state read session.

## Acceptance

- Complete records, future SQLite columns and additional frontmatter remain visible.
- Invalid content does not hide other fields or execution history.
- Markdown is readable and unsafe HTML, attributes and link schemes cannot become active.
- Reads neither write nor execute tasks; existing native approval code remains unchanged.

## Validation

All 40 solar-app tests passed, including full-record/future-column reads, malformed frontmatter, safe Markdown rendering, preserved UI history and read-only SQL checks. JS syntax, whitespace and solar-app packaging validation passed. An initial sandboxed run could not bind the temporary test port; the authorized loopback run passed. The user authorized publishing this revision to PR 23 for review. No installation, sync, merge, release or edits to other PR branches. Browser acceptance on an installed client is not claimed.
