CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  actor TEXT NOT NULL,
  workspace_root TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
  thread_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  scope_layer TEXT NOT NULL,
  scope_planet TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_run_id TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  thread_id TEXT,
  status TEXT NOT NULL,
  provider_requested TEXT NOT NULL,
  provider_used TEXT,
  router_id TEXT,
  pid INTEGER,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  summary TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  resolved_at TEXT,
  resolution_note TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  path TEXT,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL
);
