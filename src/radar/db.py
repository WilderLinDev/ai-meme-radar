"""The SQLite research store: one file, one schema, append-friendly history.

Tables fall into four layers (see docs/adr/0002-sqlite-single-store.md):

* API layer: the live catalog, every call with its raw response, sync checkpoints.
* Normalized Ge Fei data: keywords, launches, hosted sites, revenue, each as
  snapshots that are only inserted when a row's content changes.
* Research layer: trends, formats, opportunities, link events, evidence, gaps.
* Decision layer: immutable assessment revisions, human feedback, backtests,
  report states and the Lark document map.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 2  # 2: unique evidence ref, feedback.ingested_day, backtest outcome_day, research_days

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_catalog (
  id INTEGER PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  sha TEXT NOT NULL,
  tool_count INTEGER NOT NULL,
  tools_json TEXT NOT NULL,
  openapi_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tools (
  tool_id TEXT PRIMARY KEY,
  grp TEXT NOT NULL,
  title TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  price_label TEXT NOT NULL,
  params_json TEXT NOT NULL,
  required_json TEXT NOT NULL,
  source TEXT NOT NULL,
  catalog_id INTEGER NOT NULL REFERENCES api_catalog(id)
);
CREATE TABLE IF NOT EXISTS api_calls (
  id INTEGER PRIMARY KEY,
  tool_id TEXT NOT NULL,
  method TEXT NOT NULL,
  url TEXT NOT NULL,
  params_json TEXT NOT NULL,
  params_key TEXT NOT NULL,
  status_code INTEGER,
  ok INTEGER NOT NULL,
  request_id TEXT,
  credits_charged REAL,
  error_code TEXT,
  error TEXT,
  response_json TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  run_day TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS api_calls_key ON api_calls(params_key, ok, finished_at);
CREATE TABLE IF NOT EXISTS sync_items (
  kind TEXT NOT NULL,
  item_key TEXT NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  remote_at TEXT,
  last_call_id INTEGER,
  last_error TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (kind, item_key)
);

CREATE TABLE IF NOT EXISTS gefei_batches (
  service TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  finished_at TEXT,
  item_count INTEGER,
  page_url TEXT,
  summary_json TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (service, batch_id)
);
CREATE TABLE IF NOT EXISTS keywords (
  keyword TEXT PRIMARY KEY,
  display TEXT NOT NULL,
  slug TEXT,
  category TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS keyword_snapshots (
  id INTEGER PRIMARY KEY,
  keyword TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  kind TEXT, trend_now TEXT, heat_ratio REAL, growth_pct REAL,
  appear_date TEXT, burst_date TEXT, pushed_on TEXT,
  page_count INTEGER, targeted_count INTEGER,
  verdict TEXT, verdict_suggestion TEXT,
  data_json TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS keyword_snapshots_kw ON keyword_snapshots(keyword, captured_at);
CREATE TABLE IF NOT EXISTS keyword_details (
  id INTEGER PRIMARY KEY,
  keyword TEXT NOT NULL,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  data_json TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS launches (
  id INTEGER PRIMARY KEY,
  batch_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  source TEXT, title TEXT, url TEXT, domain TEXT, posted_at TEXT,
  category TEXT, purpose TEXT, audience TEXT, motive_type TEXT, keyword TEXT,
  monetization TEXT, monthly_traffic TEXT, domain_registered TEXT,
  data_json TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS launches_key ON launches(batch_id, item_key, captured_at);
CREATE TABLE IF NOT EXISTS hosted_site_snapshots (
  id INTEGER PRIMARY KEY,
  batch_id TEXT NOT NULL,
  period TEXT NOT NULL,
  site TEXT NOT NULL,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  platform TEXT, title TEXT, description TEXT,
  peak_clicks REAL, latest28_clicks REAL,
  data_json TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS hosted_site_key ON hosted_site_snapshots(site, captured_at);
CREATE TABLE IF NOT EXISTS hosted_keyword_snapshots (
  id INTEGER PRIMARY KEY,
  batch_id TEXT NOT NULL,
  period TEXT NOT NULL,
  keyword TEXT NOT NULL,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  site_count REAL, peak_clicks REAL, latest28_clicks REAL,
  data_json TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS hosted_kw_key ON hosted_keyword_snapshots(keyword, captured_at);
CREATE TABLE IF NOT EXISTS revenue_months (
  month TEXT PRIMARY KEY,
  has_monthly INTEGER NOT NULL,
  dates_28d_json TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revenue_channel_snapshots (
  id INTEGER PRIMARY KEY,
  month TEXT NOT NULL,
  period TEXT NOT NULL,
  host TEXT, channel TEXT, direction TEXT,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  data_json TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revenue_site_snapshots (
  id INTEGER PRIMARY KEY,
  month TEXT NOT NULL,
  period TEXT NOT NULL,
  domain TEXT NOT NULL,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  global_rank REAL, category TEXT,
  data_json TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revenue_site_key ON revenue_site_snapshots(domain, captured_at);
CREATE TABLE IF NOT EXISTS sites (
  domain TEXT PRIMARY KEY,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  sources_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_docs (
  id INTEGER PRIMARY KEY,
  tool_id TEXT NOT NULL,
  query TEXT NOT NULL,
  call_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  content_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
  kind TEXT NOT NULL,
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  data_json TEXT NOT NULL,
  first_seen_day TEXT NOT NULL,
  updated_day TEXT NOT NULL,
  PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS entity_keys (
  norm TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS link_events (
  id INTEGER PRIMARY KEY,
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  relation TEXT NOT NULL,
  action TEXT NOT NULL,
  origin TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  day TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,
  ref TEXT,
  entity TEXT NOT NULL,
  channel TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT NOT NULL DEFAULT '',
  metric TEXT NOT NULL DEFAULT '',
  value REAL,
  unit TEXT NOT NULL DEFAULT '',
  region TEXT NOT NULL DEFAULT '',
  sample_size INTEGER,
  metric_definition TEXT NOT NULL DEFAULT '',
  collected_at TEXT NOT NULL,
  confidence TEXT NOT NULL,
  tag TEXT NOT NULL,
  api_call_id INTEGER,
  note TEXT NOT NULL DEFAULT '',
  fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS evidence_entity ON evidence(entity, metric, region, collected_at);
CREATE UNIQUE INDEX IF NOT EXISTS evidence_ref ON evidence(ref) WHERE ref IS NOT NULL;
CREATE TABLE IF NOT EXISTS research_days (
  day TEXT PRIMARY KEY,
  notes TEXT NOT NULL,
  social_coverage_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gaps (
  day TEXT NOT NULL,
  source TEXT NOT NULL,
  note TEXT NOT NULL,
  origin TEXT NOT NULL,
  PRIMARY KEY (day, source, note)
);

CREATE TABLE IF NOT EXISTS assessments (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,
  entity TEXT NOT NULL,
  revision INTEGER NOT NULL,
  author TEXT NOT NULL,
  lifecycle TEXT NOT NULL,
  decision TEXT NOT NULL,
  priority TEXT NOT NULL,
  confidence TEXT NOT NULL,
  body_json TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (day, entity, revision)
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  entity TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT NOT NULL,
  reason TEXT NOT NULL,
  author TEXT NOT NULL,
  source_file TEXT NOT NULL,
  ingested_day TEXT NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS backtest_results (
  system TEXT NOT NULL,
  assessment_id INTEGER NOT NULL REFERENCES assessments(id),
  horizon_days INTEGER NOT NULL,
  series_json TEXT NOT NULL,
  baseline_value REAL,
  baseline_at TEXT,
  outcome_value REAL,
  outcome_at TEXT,
  outcome_day TEXT,
  change_pct REAL,
  outcome TEXT NOT NULL,
  detail TEXT NOT NULL,
  evaluated_at TEXT NOT NULL,
  PRIMARY KEY (system, assessment_id)
);

CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,
  stage TEXT NOT NULL,
  event TEXT NOT NULL,
  at TEXT NOT NULL,
  seconds REAL,
  commit_sha TEXT,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS report_states (
  day TEXT NOT NULL,
  entity TEXT NOT NULL,
  state_json TEXT NOT NULL,
  PRIMARY KEY (day, entity)
);
CREATE TABLE IF NOT EXISTS reports (
  key TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  day TEXT NOT NULL,
  entity TEXT,
  title TEXT NOT NULL,
  path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  written_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lark_docs (
  doc_key TEXT PRIMARY KEY,
  doc_id TEXT,
  url TEXT,
  synced_hash TEXT,
  synced_report TEXT,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  synced_at TEXT
);
"""


class SchemaError(RuntimeError):
    pass


def connect(path: Path) -> sqlite3.Connection:
    """Open the store. An empty file is initialized; a different schema version is refused.

    There are no migrations: when SCHEMA_VERSION changes, move the old radar.db aside and start a
    fresh one (research data is rebuilt from Ge Fei sync and new research, never migrated).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; use tx() for atomic blocks
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0
        if version == 0 and has_tables:
            raise SchemaError(f"{path} has tables but no AI Meme Radar schema version; it is not a radar database. "
                              f"Point AMR_DATA_DIR elsewhere or move the file aside.")
        if version not in (0, SCHEMA_VERSION):
            raise SchemaError(f"{path} has schema version {version}; this code needs {SCHEMA_VERSION}. "
                              f"There are no migrations: move the file aside and run again to start a fresh store.")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        if version == 0:
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    except BaseException:
        conn.close()
        raise
    return conn


class tx:
    """`with tx(conn):` runs the block in one transaction."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, exc_type, *_):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha(v: Any) -> str:
    text = v if isinstance(v, str) else dumps(v)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def insert(conn: sqlite3.Connection, table: str, row: dict) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    return int(cur.lastrowid)


def rows(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, tuple(params))]


def one(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> dict | None:
    r = conn.execute(sql, tuple(params)).fetchone()
    return dict(r) if r else None
