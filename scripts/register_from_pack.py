#!/usr/bin/env python3
"""One-off: register memes judged in an old meme pack, with evidence, into data/memes.csv.

    uv run python scripts/register_from_pack.py --pack <meme_pack_D.json> --old-tracker <meme_daily_tracker.csv> \
        --heat <heat_D.csv> --day D [--only id,id] [--evidence data/legacy/registry-evidence-D.csv]

A meme is registered only when every required registry field has a source:
  id            pack id, snake -> kebab, must be valid and unused
  name/name_zh  pack name / name_zh (verbatim)
  cc_hashtags   pack cc_hashtags (verbatim, normalised); must not belong to another meme
  primary_metric  the old tracker's primary_heat_metric for (D, pack id), which must be a radar metric
                  and have at least one complete reading for that meme in the day's heat file
                  (cc_index_30d additionally needs the tracker's cc_region; otherwise not registered)
  first_seen    D (first report that judged it)
Existing rows are never changed. Rerunning is a no-op for ids already registered.
"""
from __future__ import annotations

import argparse, csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from radar.registry import COLUMNS, ID_RE, Registry, norm_hashtag  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--pack", type=Path, required=True)
ap.add_argument("--old-tracker", type=Path, required=True)
ap.add_argument("--heat", type=Path, required=True)
ap.add_argument("--day", required=True)
ap.add_argument("--only", default="")
ap.add_argument("--evidence", type=Path)
a = ap.parse_args()

reg_path = ROOT / "data" / "memes.csv"
registry = Registry.load(reg_path)
pack = json.loads(a.pack.read_text(encoding="utf-8"))
with a.old_tracker.open(encoding="utf-8-sig", newline="") as f:
    old = {r["canonical_id"]: r for r in csv.DictReader(f) if r["date"] == a.day}
with a.heat.open(encoding="utf-8-sig", newline="") as f:
    heat = list(csv.DictReader(f))
only = {x.strip() for x in a.only.split(",") if x.strip()}
METRICS = {"viralremix_new_videos", "x_posts", "cc_index_30d", "none"}
EQ = {"none_daily_volume": "none"}
used_tags = dict(registry.by_hashtag)

with reg_path.open(encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))
evidence = []
for m in pack["memes"]:
    rid = m["id"].replace("_", "-")
    if rid in registry or (only and rid not in only):
        continue
    why, ev = [], {}
    if not ID_RE.match(rid):
        why.append(f"id {rid!r} not kebab-case")
    t = old.get(m["id"])
    metric = EQ.get(t["primary_heat_metric"], t["primary_heat_metric"]) if t else ""
    if not t:
        why.append("no old tracker row for this day")
    elif metric not in METRICS:
        why.append(f"old metric {t['primary_heat_metric']!r} is not a radar primary metric")
    elif metric == "cc_index_30d":
        why.append("cc_index_30d needs a primary_region with same-capture evidence; not auto-registered")
    names = {m.get("name"), m.get("remix_key")} - {None, ""}
    pts = [r for r in heat if r["meme"] in names and r["metric"] == metric and r["complete"] == "True"]
    if metric not in ("none", "") and not pts:
        why.append(f"no complete {metric} reading in {a.heat.name}")
    tags = [norm_hashtag(x) for x in m.get("cc_hashtags") or []]
    clash = [x for x in tags if x in used_tags]
    if clash:
        why.append(f"hashtags already belong to another meme: {clash}")
    if not m.get("name"):
        why.append("no name")
    row = {"id": rid, "name": m.get("name", ""), "name_zh": m.get("name_zh", ""), "aliases": "",
           "cc_hashtags": "|".join(tags), "primary_metric": metric, "primary_region": "",
           "first_seen": a.day,
           "notes": (t["primary_heat_source"] if t else "") + f"（{a.pack.name} 登记）"}
    evidence.append({"id": rid, "registered": "no" if why else "yes", "reason": "; ".join(why),
                     "name_src": f"{a.pack.name} memes[id={m['id']}].name", "metric_src":
                     f"{a.old_tracker.name} {a.day} {m['id']} primary_heat_metric={t['primary_heat_metric'] if t else ''}",
                     "heat_points": len(pts), "heat_dates": ",".join(sorted({p['date'] for p in pts})),
                     "cc_hashtags": "|".join(tags), "verdict_that_day": m.get("verdict", "")})
    if not why:
        rows.append(row)
        for x in tags:
            used_tags[x] = rid

rows.sort(key=lambda r: r["id"])
with reg_path.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
Registry.load(reg_path)  # validates ids, duplicates and hashtag ownership
if a.evidence:
    a.evidence.parent.mkdir(parents=True, exist_ok=True)
    old_ev = []
    if a.evidence.is_file():
        with a.evidence.open(encoding="utf-8", newline="") as f:
            old_ev = [r for r in csv.DictReader(f) if r["id"] not in {e["id"] for e in evidence}]
    allev = sorted(old_ev + evidence, key=lambda r: r["id"])
    with a.evidence.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allev[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(allev)
for e in evidence:
    print(f"{e['id']:26} {e['registered']:3} {e['metric_src'].split('=')[-1]:22} pts={e['heat_points']:<3} {e['reason']}")
