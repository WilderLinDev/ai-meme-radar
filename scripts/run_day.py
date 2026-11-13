#!/usr/bin/env python3
"""AI Meme Radar: the one execution entry point.

    uv run python scripts/run_day.py run    [DAY] [--resync] [--services keywords,launches,hosted,revenue]
    uv run python scripts/run_day.py call   TOOL ['{"param": ...}'] [--purpose TEXT] [--fresh | --max-age-days N]
    uv run python scripts/run_day.py tools  [GROUP]
    uv run python scripts/run_day.py status [DAY]

run     Runs every stage that can run (preflight, sync, discover, research, scaffold, decide,
        backtest, report, publish) and resumes from what is already done. Exit 0 = delivered,
        2 = waiting for an agent file in <data>/work/DAY/, 1 = failed (see the message),
        3 = another run is in progress (single-instance lock on <data>/run.lock).
call    Calls one Ge Fei tool through the recorded client: request, response, requestId and credits
        are stored in SQLite; an identical successful call inside the reuse window is served from
        SQLite instead. Prints {"call_id", "cached", "credits", "data"} as JSON.
tools   Lists the live Ge Fei catalog (refreshed from /api/v1/tools and /api/openapi.json).
status  Last event of every stage for DAY, sync units waiting for retry, the daily report path, and every
        Lark document: name, type, status (synced/stale/failed/unpublished), URL, local path, error.

DAY defaults to today in Asia/Shanghai. Settings: environment variables (GEFEI_API_TOKEN, AMR_CONFIG_DIR,
AMR_DATA_DIR, AMR_REPORTS_DIR) override $AMR_CONFIG_DIR/settings.toml (default
~/.config/ai-meme-radar/settings.toml), which overrides defaults. Data lives outside the repo.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from radar import pipeline  # noqa: E402
from radar.config import ConfigError, Paths, load_settings, today  # noqa: E402
from radar.db import SchemaError  # noqa: E402
from radar.gefei.client import Client, GefeiError  # noqa: E402
from radar.gefei.sync import SERVICES  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("day", nargs="?")
    r.add_argument("--resync", action="store_true", help="pull Ge Fei data services again even if synced today")
    r.add_argument("--services", default=",".join(SERVICES))
    c = sub.add_parser("call")
    c.add_argument("tool")
    c.add_argument("params", nargs="?", default="{}")
    c.add_argument("--purpose", default="")
    c.add_argument("--fresh", action="store_true", help="never reuse a stored response")
    c.add_argument("--max-age-days", type=float)
    t = sub.add_parser("tools")
    t.add_argument("group", nargs="?")
    s = sub.add_parser("status")
    s.add_argument("day", nargs="?")
    a = ap.parse_args(argv)

    try:
        settings = load_settings()
        paths = Paths.resolve(settings)
        conn = pipeline.open_db(paths)
    except (ConfigError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    day = date.fromisoformat(a.day) if getattr(a, "day", None) else today()

    if a.cmd == "run":
        services = tuple(x for x in a.services.split(",") if x)
        bad = [x for x in services if x not in SERVICES]
        if bad:
            ap.error(f"unknown services {bad}; choose from {SERVICES}")
        ctx = pipeline.Context(day=day, settings=settings, paths=paths, conn=conn, resync=a.resync, services=services)
        return pipeline.run(ctx)

    if a.cmd == "status":
        pipeline.status(conn, day)
        return 0

    client = Client(conn, settings.token, settings.gefei.base_url, run_day=today())
    if a.cmd == "tools":  # the catalog is public; no token needed
        try:
            tools = client.refresh_catalog(force=True)
        except GefeiError as e:
            print(settings.redact(str(e)), file=sys.stderr)
            return 1
        for tool in sorted(tools.values(), key=lambda x: (x.group, x.id)):
            if a.group and tool.group != a.group:
                continue
            req = ",".join(tool.required)
            print(f"{tool.group:9} {tool.id:28} {tool.method:4} {tool.path:36} req[{req}] "
                  f"params[{','.join(tool.params)}] {tool.price_label}")
        print(f"{len(tools)} tools")
        return 0

    try:
        settings.require_token()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        params = json.loads(a.params)
    except json.JSONDecodeError as e:
        print(f"params must be a JSON object: {e}", file=sys.stderr)
        return 1
    max_age = timedelta(0) if a.fresh else (timedelta(days=a.max_age_days) if a.max_age_days is not None else None)
    try:
        client.refresh_catalog()
        res = client.call(a.tool, params, purpose=a.purpose, max_age=max_age)
    except (GefeiError, KeyError, ValueError) as e:
        print(settings.redact(str(e)), file=sys.stderr)
        return 1
    print(json.dumps({"call_id": res.call_id, "cached": res.cached, "request_id": res.request_id,
                      "credits": res.credits, "data": res.data, "markdown": res.body.get("markdown")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
