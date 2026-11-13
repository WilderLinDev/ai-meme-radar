"""The strict preflight gate: every prerequisite is checked, all failures are reported together,
and no workflow stage starts until everything passes."""
from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from radar import db, pipeline, preflight
from radar.config import REPO, ConfigError, load_settings
from radar.preflight import BROWSER_CHECKS
from conftest import DAY1, FakeLark, browser_report, make_ctx, ready, research_doc, write

sys.path.insert(0, str(REPO / "scripts"))


def gate(paths, conn, settings, fake, lk=None, **kw):
    said: list[str] = []
    c = make_ctx(paths, conn, settings, fake, lk or FakeLark(), say=said.append, **kw)
    code = pipeline.run(c)
    report = json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text(encoding="utf-8"))
    return code, report, "\n".join(said)


def failed(report) -> dict[str, dict]:
    return {c["name"]: c for c in report["checks"] if not c["ok"]}


def stages_started(conn) -> list[str]:
    return [r["stage"] for r in db.rows(conn, "SELECT DISTINCT stage FROM run_events WHERE stage != 'preflight'")]


def assert_blocked(conn, fake, code):
    """NOT READY, and nothing after the gate ran: no stage event, no sync call, no candidates."""
    assert code == pipeline.NOT_READY
    assert stages_started(conn) == []
    assert not [p for m, p, q, b in fake.calls if "/batches/" in p and p.count("/") > 4]


# ---- the happy path ----
def test_all_checks_pass_then_the_full_workflow_starts(paths, conn, settings, fake):
    code, report, said = gate(paths, conn, settings, fake)
    assert report["ready"] and report["failed"] == []
    areas = {c["area"] for c in report["checks"]}
    assert areas == {"local", "gefei", "lark", "browser"}
    assert {c["name"] for c in report["checks"] if c["area"] == "browser"} == set(BROWSER_CHECKS)
    assert "PREFLIGHT 2026-11-13: READY" in said
    assert code == pipeline.WAITING  # went straight on: sync and discover ran, now waiting for research.json
    assert {"sync", "discover", "research"} <= set(stages_started(conn))


def test_gate_spends_no_research_credits_and_writes_nothing_to_lark(paths, conn, settings, fake):
    lk = FakeLark()
    gate(paths, conn, settings, fake, lk)
    pre = db.rows(conn, "SELECT tool_id, credits_charged FROM api_calls WHERE purpose='preflight'")
    assert {r["tool_id"] for r in pre} == {"me", "keyword_batches", "launch_batches", "hosted_batches",
                                           "income_months_v2"}
    assert sum(r["credits_charged"] or 0 for r in pre) == 0
    assert lk.publishes == []  # nothing created or updated by the gate (no reports yet either)


# ---- Ge Fei ----
def test_missing_gefei_token(paths, conn, settings, fake):
    settings.gefei.token = ""
    code, report, said = gate(paths, conn, settings, fake)
    f = failed(report)
    assert "GEFEI_API_TOKEN" in f["Ge Fei token"]["fix"]
    assert f["Ge Fei authentication"]["result"] == "not verified"  # dependent checks are failed, not skipped
    assert "Ge Fei credits" in f and "Ge Fei data services" in f
    assert_blocked(conn, fake, code)


def test_invalid_gefei_authentication(paths, conn, settings, fake):
    fake.reject_token = True
    code, report, said = gate(paths, conn, settings, fake)
    f = failed(report)
    assert f["Ge Fei authentication"]["reason"] == "the token was rejected"
    assert "wc_mcp_test" not in json.dumps(report) and "wc_mcp_test" not in said
    assert_blocked(conn, fake, code)


def test_gefei_connectivity_failure(paths, conn, settings, fake):
    fake.offline = True
    code, report, said = gate(paths, conn, settings, fake)
    f = failed(report)
    assert "unreachable" in f["Ge Fei endpoint and catalog"]["reason"]
    assert {"Ge Fei authentication", "Ge Fei credits", "Ge Fei data services"} <= set(f)
    assert_blocked(conn, fake, code)


def test_insufficient_credits(paths, conn, settings, fake):
    fake.balance = 12
    settings.gefei.min_credits = 50
    code, report, _ = gate(paths, conn, settings, fake)
    assert set(failed(report)) == {"Ge Fei credits"}
    assert "balance 12" in failed(report)["Ge Fei credits"]["result"]
    assert_blocked(conn, fake, code)


def test_unreported_balance_is_unverified_not_passed(paths, conn, settings, fake):
    fake.balance = None
    code, report, _ = gate(paths, conn, settings, fake)
    assert set(failed(report)) == {"Ge Fei credits"}
    assert_blocked(conn, fake, code)


def test_locked_data_service(paths, conn, settings, fake):
    fake.locked.add("/api/v1/hosted/batches")
    code, report, _ = gate(paths, conn, settings, fake)
    assert set(failed(report)) == {"Ge Fei data services"}
    assert "hosted: HTTP 403 data_locked" in failed(report)["Ge Fei data services"]["result"]
    assert_blocked(conn, fake, code)


# ---- browser and social platforms (agent-reported) ----
def test_browser_unavailable(paths, conn, settings, fake):
    code, report, _ = gate(paths, conn, settings, fake, browser=False)  # the agent wrote no browser report
    assert set(failed(report)) == set(BROWSER_CHECKS)
    assert all("preflight.browser.json is missing" in c["reason"] for c in failed(report).values())
    assert_blocked(conn, fake, code)


def test_browser_reported_disconnected(paths, conn, settings, fake):
    lk = FakeLark()
    c = make_ctx(paths, conn, settings, fake, lk, say=lambda s: None)
    ready(paths, Browser_connection={"status": "failed", "access": "unreachable", "urls": [],
                                     "result": "no browser tab could be opened", "reason": "extension disconnected",
                                     "fix": "reconnect the browser extension"})
    assert_blocked(conn, fake, pipeline.run(c))
    f = failed(json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text()))
    assert set(f) == {"Browser connection"} and f["Browser connection"]["fix"] == "reconnect the browser extension"


@pytest.mark.parametrize("platform", ["TikTok", "CapCut", "Instagram", "X", "YouTube", "Reddit", "Creative Center",
                                      "Watchlist"])
def test_each_required_platform_unavailable(paths, conn, settings, fake, platform):
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    ready(paths, **{platform.replace(" ", "_"): {"status": "failed", "access": "blocked",
                                                  "reason": "page did not load", "fix": "check access"}})
    assert_blocked(conn, fake, pipeline.run(c))
    f = failed(json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text()))
    assert set(f) == {platform}


def test_required_login_missing(paths, conn, settings, fake):
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    ready(paths, Instagram={"status": "failed", "access": "login_required", "result": "redirected to login",
                            "reason": "Instagram asks to log in", "fix": ""})
    assert_blocked(conn, fake, pipeline.run(c))
    f = failed(json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text()))
    assert set(f) == {"Instagram"} and "log in" in f["Instagram"]["fix"]


@pytest.mark.parametrize("override,why", [
    ({"access": "login_required"}, "marked pass with access login_required"),
    ({"urls": ["https://www.tiktok.com/"]}, "not a homepage"),
    ({"urls": ["https://www.youtube.com/results?search_query=x"]}, "tiktok.com"),
])
def test_a_pass_that_does_not_hold_up_is_failed(paths, conn, settings, fake, override, why):
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    ready(paths, TikTok=override)
    assert_blocked(conn, fake, pipeline.run(c))
    f = failed(json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text()))
    assert set(f) == {"TikTok"} and why in f["TikTok"]["reason"]


def test_watchlist_pass_must_open_selected_profiles(paths, conn, settings, fake):
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    ready(paths, Watchlist={"urls": ["https://www.tiktok.com/@memescreens"]})  # no Instagram profile opened
    assert_blocked(conn, fake, pipeline.run(c))
    f = failed(json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text()))
    assert set(f) == {"Watchlist"} and "Instagram" in f["Watchlist"]["reason"]


def test_stale_browser_report_is_not_accepted(paths, conn, settings, fake):
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    old = browser_report()
    old["day"], old["checked_at"] = "2026-11-12", "2026-11-12T08:00:00+08:00"
    write(paths.work(DAY1) / preflight.BROWSER_FILE, old)
    assert_blocked(conn, fake, pipeline.run(c))
    f = failed(json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text()))
    assert set(f) == set(BROWSER_CHECKS) and all(x["result"] == "stale" for x in f.values())


# ---- Lark ----
def test_lark_cli_unavailable(paths, conn, settings, fake):
    lk = FakeLark()
    lk.installed = False
    code, report, _ = gate(paths, conn, settings, fake, lk, which=lambda n: None if n == "lark-cli" else f"/bin/{n}")
    f = failed(report)
    assert f["lark-cli executable"]["result"] == "not on PATH"
    assert {"Lark authentication", "Lark daily destination", "Lark opportunity destination",
            "Lark document commands", "Lark existing documents"} <= set(f)
    assert_blocked(conn, fake, code)


def test_lark_authentication_failure(paths, conn, settings, fake):
    lk = FakeLark()
    lk.logged_in = False
    code, report, _ = gate(paths, conn, settings, fake, lk)
    f = failed(report)
    assert "lark-cli auth login" in f["Lark authentication"]["fix"]
    assert f["Lark daily destination"]["result"] == "not verified"
    assert_blocked(conn, fake, code)


def test_lark_destination_missing_or_not_editable(paths, conn, settings, fake):
    lk = FakeLark()
    del lk.nodes["wikiOpp"]  # opportunity node does not exist
    lk.editable.discard("wikiDaily")  # daily node exists but is read-only for this identity
    code, report, _ = gate(paths, conn, settings, fake, lk)
    f = failed(report)
    assert f["Lark daily destination"]["reason"] == "no edit permission"
    assert f["Lark opportunity destination"]["reason"] == "not found"
    assert_blocked(conn, fake, code)


def test_lark_destination_not_configured(paths, conn, settings, fake):
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    c.settings.lark.daily_parent = ""
    assert_blocked(conn, fake, pipeline.run(c))
    f = failed(json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text()))
    assert "daily_parent is empty" in f["Lark settings"]["result"]
    assert set(f) == {"Lark settings", "Lark daily destination"}  # login and the opportunity node are still checked


def test_existing_document_that_lost_edit_rights_blocks_the_run(paths, conn, settings, fake):
    from conftest import DEEP, assessment
    lk = FakeLark()
    write(paths.work(DAY1) / "research.json", research_doc())
    write(paths.work(DAY1) / "assessments.json", {"day": DAY1.isoformat(), "assessments": [
        assessment("opportunity:baby-dance-template", decision="build", priority="P0", deep=DEEP, next_steps=["go"],
                   tracked=None)]})
    assert pipeline.run(make_ctx(paths, conn, settings, fake, lk)) == pipeline.DONE
    conn.execute("UPDATE reports SET content_hash='changed' WHERE kind='daily'")  # the daily doc is due for update
    lk.editable.discard("doc1")
    code, report, _ = gate(paths, conn, settings, fake, lk)
    assert set(failed(report)) == {"Lark existing documents"}
    assert code == pipeline.NOT_READY


# ---- local ----
def test_invalid_local_configuration(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.toml").write_text("[gefei\ntoken = 1", encoding="utf-8")
    monkeypatch.setenv("AMR_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("AMR_DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(ConfigError):
        load_settings()
    import run_day
    assert run_day.main(["run", DAY1.isoformat()]) == pipeline.NOT_READY
    out = capsys.readouterr().out
    assert "NOT READY" in out and "[FAILED] local / Settings" in out and "invalid TOML" in out
    assert "[PASS] local / Python" in out  # the independent checks still ran
    assert not (tmp_path / "data" / "radar.db").exists()


def test_database_incompatibility(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    data.mkdir()
    old = sqlite3.connect(data / "radar.db")
    old.execute("PRAGMA user_version=2")
    old.execute("CREATE TABLE t (x)")
    old.close()
    monkeypatch.setenv("AMR_CONFIG_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("AMR_DATA_DIR", str(data))
    import run_day
    assert run_day.main(["run", DAY1.isoformat()]) == pipeline.NOT_READY
    out = capsys.readouterr().out
    assert "[FAILED] local / Data folder and SQLite database" in out and "schema version 2" in out


def test_unwritable_folder_and_bad_feedback_file(paths, conn, settings, fake):
    write(paths.feedback_inbox / "pm.json", {"feedback": [{"entity": "trend:x"}]})
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    paths.work(DAY1).chmod(0o500)
    try:
        assert_blocked(conn, fake, pipeline.run(c))
    finally:
        paths.work(DAY1).chmod(0o700)
    # the report could not be written to the read-only work folder; the run still refused to start
    rep = preflight.run_checks(c)
    assert {"Feedback files"} <= {x.name for x in rep.failed}


def test_uv_missing(paths, conn, settings, fake):
    code, report, _ = gate(paths, conn, settings, fake, which=lambda n: None if n == "uv" else f"/bin/{n}")
    assert set(failed(report)) == {"uv executable"}
    assert_blocked(conn, fake, code)


# ---- consolidation, recheck, automatic continuation ----
def test_multiple_failures_are_reported_together(paths, conn, settings, fake):
    settings.gefei.token = ""
    lk = FakeLark()
    lk.logged_in = False
    code, report, said = gate(paths, conn, settings, fake, lk, browser=False)
    f = failed(report)
    assert {"Ge Fei token", "Lark authentication", "TikTok", "Instagram", "Watchlist"} <= set(f)
    assert said.count("[FAILED]") == len(f) and "No stage was started" in said
    for c in f.values():
        assert c["reason"] and c["fix"]  # every failure says why and what to do
    assert_blocked(conn, fake, code)


def test_recheck_after_user_fix_starts_the_workflow_by_itself(paths, conn, settings, fake):
    lk = FakeLark()
    lk.logged_in = False
    fake.balance = 3
    c = make_ctx(paths, conn, settings, fake, lk, say=lambda s: None)
    ready(paths, Instagram={"status": "failed", "access": "login_required", "reason": "login wall", "fix": "log in"})
    assert_blocked(conn, fake, pipeline.run(c))

    # the user logs in to Lark and Instagram and tops up credits; the agent redoes the failed browser check
    lk.logged_in, fake.balance = True, 500
    ready(paths)
    assert pipeline.run(c) == pipeline.WAITING  # same command: rechecked, READY, then the workflow ran on its own
    report = json.loads((paths.work(DAY1) / preflight.REPORT_FILE).read_text())
    assert report["ready"]
    assert {"sync", "discover", "research"} <= set(stages_started(conn))
    assert (paths.work(DAY1) / "candidates.json").is_file()


def test_gate_recheck_does_not_rerun_finished_stages(paths, conn, settings, fake):
    lk = FakeLark()
    c = make_ctx(paths, conn, settings, fake, lk, say=lambda s: None)
    assert pipeline.run(c) == pipeline.WAITING  # synced, waiting for research.json
    lk.logged_in = False  # a later invocation finds Lark logged out: blocked before anything else
    n = len(fake.calls)
    assert pipeline.run(c) == pipeline.NOT_READY
    lk.logged_in = True
    assert pipeline.run(c) == pipeline.WAITING
    detail = [p for m, p, q, b in fake.calls[n:] if "/batches/" in p and p.count("/") > 4]
    assert detail == []  # settled batches were not fetched again
    syncs = db.rows(conn, "SELECT note FROM run_events WHERE stage='sync' AND event IN ('done','skipped')")
    assert "already synced today" in syncs[-1]["note"]


def test_no_stage_runs_when_exactly_one_check_fails(paths, conn, settings, fake):
    write(paths.work(DAY1) / "research.json", research_doc())  # even with agent input waiting, nothing ingests
    c = make_ctx(paths, conn, settings, fake, FakeLark(), say=lambda s: None)
    ready(paths, Reddit={"status": "failed", "access": "blocked", "reason": "rate limited", "fix": "retry later"})
    assert_blocked(conn, fake, pipeline.run(c))
    assert db.one(conn, "SELECT COUNT(*) n FROM entities")["n"] == 0
    assert not (paths.work(DAY1) / "candidates.json").exists()
    assert db.one(conn, "SELECT COUNT(*) n FROM reports")["n"] == 0


def test_status_shows_last_preflight(paths, conn, settings, fake):
    gate(paths, conn, settings, fake, browser=False)
    out: list[str] = []
    pipeline.status(conn, DAY1, out.append, paths=paths)
    assert any(line.startswith("preflight: NOT READY (failed: Browser connection") for line in out)
