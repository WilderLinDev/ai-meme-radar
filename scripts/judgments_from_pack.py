#!/usr/bin/env python3
"""One-off: turn a pre-radar meme pack (the day's recorded judgments) into reports/D/judgments.json.

    uv run python scripts/judgments_from_pack.py --pack <meme_pack_D.json> [--excluded-csv <cc_excluded.csv>] \
        [--skip id,id --skip-reason "..."]

Every value comes from the pack (or the old run's cc_excluded.csv); nothing is re-judged:
  verdict/part/reason/window/scores/score_notes/what/origin/risks/howto  verbatim
  ignite_date   the leading ISO date of the pack's ignite_date text (full text kept in ignite_note)
  links         pack originals + trackers;  heat_note = heat_sources + heat_gaps;  share_note = share_read
  competition   capcut, capcut_url, sites (name -> label), judgment; watchlist evidence appended to judgment
  override_reason  only when the recorded verdict differs from radar's suggested verdict: the pack has no
                   separate field, so it quotes the recorded reason, labelled as such
  excluded_hashtags  pack excluded_cc reasons, then cc_excluded.csv rows grouped by their recorded reason
--skip leaves memes out (their CC hashtags go to an excluded group with --skip-reason).
Pack fields with no radar slot (howto.framed, examples, cc_audience, days_hot*, peak_status*, backtest_line,
score_delta, verdict_change, source_tag, tag_url) are dropped: radar recomputes or does not use them.
"""
from __future__ import annotations

import argparse, csv, json, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from radar.judgments import Judgments, MemeJudgment, Scores  # noqa: E402
from radar.registry import Registry, norm_hashtag  # noqa: E402
from radar.scoring import suggested_verdict  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--pack", type=Path, required=True)
ap.add_argument("--excluded-csv", type=Path)
ap.add_argument("--skip", default="")
ap.add_argument("--skip-reason", default="")
ap.add_argument("--out", type=Path)
a = ap.parse_args()

pack = json.loads(a.pack.read_text(encoding="utf-8"))
day = pack["report_date"]
registry = Registry.load(ROOT / "data" / "memes.csv")
skip = {x.strip() for x in a.skip.split(",") if x.strip()}
V = {"做": "make", "观望": "watch", "不做": "skip"}
D = {"热度": "heat", "趋势": "trend", "分享率": "share", "竞争": "competition", "窗口": "window"}
ISO = re.compile(r"^(\d{4}-\d{2}-\d{2})(?!\d)")

memes, skipped_tags = [], []
for m in pack["memes"]:
    rid = m["id"].replace("_", "-")
    if rid in skip:
        skipped_tags += registry[rid].cc_hashtags if rid in registry else [norm_hashtag(t) for t in m.get("cc_hashtags") or []]
        continue
    if rid not in registry:
        sys.exit(f"{rid} is not registered; register it first or --skip it")
    notes = m.get("score_notes") or {}
    scores = Scores.model_validate({D[k]: {"score": m["scores"][k], "note": notes.get(k, "")} for k in D})
    assert scores.total == m["scores"]["total"], rid
    comp = m.get("competition") or {}
    judgment = comp.get("judgment", "")
    wl = [w["label"] + " " + w["url"] for w in comp.get("watchlist") or []]
    if wl or comp.get("watchlist_none"):
        judgment += ("\n监控号：" + "；".join(wl) if wl else "\n" + comp["watchlist_none"])
    ign = (m.get("ignite_date") or "").strip()
    howto = {k: v for k, v in (m.get("howto") or {}).items() if k != "framed"}
    verdict = V[m["verdict"]]
    override = ""
    if verdict != suggested_verdict(scores):
        override = "（原日报未单列推翻理由，以下为当日记录的结论理由）" + m["reason"]
    hs = "；".join(m.get("heat_sources") or [])
    memes.append(MemeJudgment(
        meme_id=rid, part=m.get("part", "main"), verdict=verdict, override_reason=override,
        reason=m["reason"], window_note=m.get("window") or "", scores=scores,
        ignite_date=ISO.match(ign).group(1) if ISO.match(ign) else None, ignite_note=ign,
        what=m.get("what") or "", origin=m.get("origin") or "",
        links=[{"label": x["label"], "url": x["url"]} for x in (m.get("originals") or []) + (m.get("trackers") or [])],
        heat_note=hs + (("。缺口：" + m["heat_gaps"]) if m.get("heat_gaps") else ""),
        share_note=m.get("share_read") or "",
        competition={"capcut": comp.get("capcut") or "", "capcut_url": comp.get("capcut_url") or "",
                     "sites": [{"label": s.get("name") or s.get("label", ""), "url": s["url"]} for s in comp.get("sites") or []],
                     "judgment": judgment},
        howto=howto, risks=m.get("risks") or [],
    ))

groups: dict[str, list[str]] = defaultdict(list)
seen: set[str] = set()
def add(tag: str, reason: str):
    t = norm_hashtag(tag)
    if t and t not in seen:
        seen.add(t); groups[reason].append(t)
for e in pack.get("excluded_cc") or []:
    add(e["tag"], e["reason"])
if a.excluded_csv:
    with a.excluded_csv.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            add(r["hashtag"], r["reason"])
if skipped_tags:
    for t in skipped_tags:
        add(t, a.skip_reason or "migration: meme left out of this build")
notes = list(pack.get("intro_lines_zh") or [])
if pack.get("watchlist_note"):
    notes.append(pack["watchlist_note"])
notes.append(f"本 judgments.json 由 {a.pack.name} 转换（scripts/judgments_from_pack.py），结论、分数和文字均为当日记录，未重新判断。")
if skip:
    notes.append("未纳入本次 radar 构建：" + "、".join(sorted(skip)) + "。" + a.skip_reason)
j = Judgments(date=day, memes=memes, excluded_hashtags=[{"tags": v, "reason": k} for k, v in groups.items()], notes=notes)
out = a.out or ROOT / "reports" / day / "judgments.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(j.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"{out}: {len(memes)} memes, {sum(map(len, groups.values()))} excluded hashtags in {len(groups)} groups, "
      f"{sum(1 for x in memes if x.override_reason)} with quoted override_reason")
