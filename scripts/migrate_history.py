#!/usr/bin/env python3
"""One-off history migration: old meme_daily_tracker.csv + historical raw captures -> radar layout.

See docs/adr/0004. Run from the checkout so the `radar` package (tracker.COLUMNS, raw schemas,
primary heat rules, backtest.evaluate/write) is the code that computes everything:

  uv run python scripts/migrate_history.py --old-tracker <meme_daily_tracker.csv> \
      --lark-dir /workspace/lark --cc-dir /workspace/tiktok_cc [--root .] [--as-of YYYY-MM-DD]

Inputs are only read. Writes into the checkout (rerun with the same inputs gives identical files):
  data/raw/DAY/           heat.csv, cc-curves.csv for every capture day; for report days also
                          cc-top100.csv, remixes.csv, cc-audience.csv, watchlist-posts.csv, gaps.json
  data/tracker.csv        merged: existing rows are kept; a migrated row whose (date, meme_id) already
                          exists with different values is archived instead
  data/backtest.json/.csv recomputed with backtest.evaluate/write over the merged tracker
  data/legacy/            quarantine-tracker.csv (old rows verbatim + reason), quarantine-raw.csv
                          (source_file, source_line, reason, original JSON), mapping-evidence.csv,
                          tracker-evidence.csv, migration-manifest.json

Rules (documented judgement calls):
  * meme_id: exact match only. Tracker rows need BOTH kebab(canonical_id) == registry id AND the old
    `meme` text == registry name / alias / '#'+cc_hashtag. Raw names map via registry name/id/alias/#tag,
    or via a meme pack entry whose kebab(id) == registry id AND pack name == registry name
    (then the pack's name / remix_key map to that id). Ambiguous or missing -> quarantine.
  * primary metric = the registry's; old `none_daily_volume` is treated as the same basis as `none`.
    Old metric != registry metric, or (cc_index_30d) old cc_tag/cc_region != registry
    cc_hashtags[0]/primary_region -> quarantine (no re-basing).
  * Old score_* are kept; total must equal the sum and old `score`, else quarantine.
    suggested_verdict, primary value/date, share, peak status, cc_regions, days_hot are recomputed by
    radar code from migrated raw captures on or before the report day. ignite_date only when the old
    text starts with an ISO date; bounds like '不晚于 …' or prose -> empty (no days_hot).
  * One capture per (source kind, day): when a day has a base file and a later `_run2` file, run2 is
    the day's capture. For heat, v1 rows identical to run2 are covered; differing v1 rows go to
    quarantine. For CC curves, per (hashtag, region, period) the later capture is used whole and the
    earlier capture's rows for that curve go to quarantine; curves only in v1 are used from v1 intact.
    `_merged` files (mixed captures) are not used. Heat JSON twins of the CSVs are not used.
  * Heat rows: unmapped meme, cc_popularity_index_30d (CC belongs in cc-curves, same-capture rule),
    or conflicting complete readings for one (meme_id, metric, date) inside one capture -> quarantine.
  * Remixes (share facts only, report days only): the day's latest remix_stats file, rows the old run
    marked in_top_sample=yes, not originals, with a views reading; others -> quarantine with reason.
"""
from __future__ import annotations

import argparse, csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="radar checkout")
ap.add_argument("--old-tracker", type=Path, required=True)
ap.add_argument("--lark-dir", type=Path, required=True)
ap.add_argument("--cc-dir", type=Path, required=True)
ap.add_argument("--legacy-dir", type=Path, default=None, help="default: <root>/data/legacy")
ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="backtest as-of (default: latest tracker date)")
args = ap.parse_args()
sys.path.insert(0, str(args.root.resolve() / "src"))

from radar import backtest, tracker                       # noqa: E402
from radar.config import Layout, Settings                  # noqa: E402
from radar.csvio import write_rows                         # noqa: E402
from radar.judgments import MemeJudgment                   # noqa: E402
from radar.pack import compute_facts, finish_facts         # noqa: E402
from radar.pipeline import _tracker_row, PackMeme         # noqa: E402
from radar.raw import load_day, load_history               # noqa: E402
from radar.registry import Registry, norm_hashtag          # noqa: E402

ROOT = args.root.resolve()
OUT = (args.legacy_dir or ROOT / "data" / "legacy").resolve()
for target in (ROOT, OUT):
    for forbidden in (args.lark_dir.resolve(), args.cc_dir.resolve(), Path.home() / ".config"):
        if str(target).startswith(str(forbidden)):
            sys.exit(f"refusing to write under {forbidden}")
OUT.mkdir(parents=True, exist_ok=True)
layout = Layout.from_settings(ROOT, Settings())  # repo-default paths, independent of local settings
registry = Registry.load(layout.registry)
L, CC = args.lark_dir, args.cc_dir

inputs: list[Path] = []
def rows(p: Path) -> list[dict]:
    inputs.append(p)
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
def kebab(s: str) -> str:
    return s.strip().replace("_", "-")
DAY_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})(_run2)?\.(csv|json)$")
def captures(pattern: str) -> dict[str, list[Path]]:
    """day -> files, earliest capture first (base, then _run2). _merged and others ignored."""
    out: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(L.glob(pattern)):
        m = DAY_RE.search(p.name)
        if m:
            out[m.group(1)].append(p)
    for d in out:
        out[d].sort(key=lambda p: ("_run2" in p.name, p.name))
    return dict(out)

quar_raw: list[dict] = []
def qraw(src: Path, line: int, reason: str, row: dict):
    quar_raw.append({"source_file": str(src), "source_line": line, "reason": reason,
                     "original": json.dumps(row, ensure_ascii=False)})
superseded: list[str] = []
evidence: dict[str, tuple[str, str]] = {}   # raw name -> (meme_id or '', evidence)

# ---------- name -> meme_id evidence ----------
direct: dict[str, set[tuple[str, str]]] = defaultdict(set)
for m in registry.memes.values():
    direct[m.id].add((m.id, "registry id"))
    direct[m.name].add((m.id, "registry name"))
    for a in m.aliases:
        direct[a].add((m.id, "registry alias"))
    for t in m.cc_hashtags:
        direct["#" + t].add((m.id, f"registry cc_hashtag #{t}"))
for pack_path in sorted(L.glob("meme_pack_*.json")):
    inputs.append(pack_path)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    for pm in pack.get("memes", []):
        rid = kebab(pm.get("id", ""))
        if rid in registry and pm.get("name") == registry[rid].name:
            for k in {pm.get("name"), pm.get("remix_key")} - {None, ""}:
                direct[k].add((rid, f"{pack_path.name}: pack id {pm['id']} -> {rid} and pack name == registry name"))

def map_name(name: str) -> tuple[str | None, str]:
    name = (name or "").strip()
    hits = direct.get(name, set())
    if not hits and name.startswith("#"):
        hits = direct.get("#" + norm_hashtag(name), set())
    ids = {i for i, _ in hits}
    if len(ids) == 1:
        res = (ids.pop(), "; ".join(sorted(e for _, e in hits)))
    elif len(ids) > 1:
        res = (None, "ambiguous: " + ",".join(sorted(ids)))
    else:
        res = (None, "no exact match in registry or verified pack ids")
    evidence[name] = (res[0] or "", res[1])
    return res

def write_csv(path: Path, cols: list[str], data: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(data)

counts: dict = {"raw": {}}
# ---------- heat ----------
for day, files in captures("heat_*.csv").items():
    use = files[-1]
    kept: dict[tuple, list[tuple[int, dict]]] = defaultdict(list)
    for line, r in enumerate(rows(use), start=2):
        mid, _ = map_name(r["meme"])
        if r["metric"] == "cc_popularity_index_30d":
            qraw(use, line, "heat_cc_index_copy_not_used(cc from cc-curves capture)", r); continue
        if not mid:
            qraw(use, line, "unmapped_meme", r); continue
        try:
            float(r["value"]); date.fromisoformat(r["date"])
            assert r["complete"].strip().lower() in ("true", "false")
        except (ValueError, AssertionError):
            qraw(use, line, "non_numeric_value_or_bad_date/complete", r); continue
        kept[(mid, r["metric"], r["date"])].append((line, r))
    out = []
    for key in sorted(kept):
        cand = kept[key]
        complete = [c for c in cand if c[1]["complete"].strip().lower() == "true"]
        pool = complete or cand
        if len({c[1]["value"] for c in pool}) > 1:
            for line, r in cand:
                qraw(use, line, "conflicting_readings_same_capture", r)
            continue
        line, r = pool[0]
        out.append({"meme_id": key[0], "date": r["date"], "metric": r["metric"], "value": r["value"],
                    "source": f"{use.name}:{line} | {r['source']}", "complete": r["complete"]})
        for l2, r2 in cand:
            if l2 == line:
                continue
            qraw(use, l2, "duplicate_identical_reading_same_capture" if any(l2 == c[0] for c in pool)
                 else "partial_reading_superseded_by_complete_same_capture", r2)
    for older in files[:-1]:
        superseded.append(f"{older.name} (heat {day}: superseded by {use.name})")
        newer = {(x["meme"], x["metric"], x["date"]): x["value"] for x in rows(use)}
        for line, r in enumerate(rows(older), start=2):
            k = (r["meme"], r["metric"], r["date"])
            if k not in newer:
                qraw(older, line, "earlier_same_day_capture_only_reading(not mixed)", r)
            elif newer[k] != r["value"]:
                qraw(older, line, "earlier_same_day_capture_conflict(later capture used)", r)
    write_csv(layout.raw_dir(date.fromisoformat(day)) / "heat.csv",
              ["meme_id", "date", "metric", "value", "source", "complete"], out)
    counts["raw"][f"{day}/heat.csv"] = len(out)

# ---------- CC curves (one capture per curve, never mixed) ----------
REGION_RE = re.compile(r"[?&](?:region|countryCode)=([A-Z]{2})")
def curve_rows(p: Path) -> list[tuple[int, dict, dict | None, str]]:
    out = []
    for line, r in enumerate(rows(p), start=2):
        if not (r.get("value") or "").strip():
            out.append((line, r, None, "no_value(status=%s)" % r.get("status", "")))
            continue
        region = (r.get("region") or "").strip()
        if not region:
            m = REGION_RE.search(r.get("detail_url", ""))
            region = m.group(1) if m else ""
        d = r["date"].strip()
        if re.fullmatch(r"\d{2}/\d{2}/\d{2}", d):
            d = datetime.strptime(d, "%d/%m/%y").date().isoformat()
        if not region or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            out.append((line, r, None, "curve_row_without_region_or_date")); continue
        detail = r.get("detail_id") or (re.search(r"/hashtag/(\d+)", r.get("detail_url", "")) or [None, ""])[1]
        out.append((line, r, {"hashtag": norm_hashtag(r["hashtag"]), "region": region, "period": r["period_days"],
                              "date": d, "value": r["value"], "detail_id": detail}, ""))
    return out
curve_src: dict[tuple, str] = {}
for day, files in captures("cc_hashtag_trends_*.csv").items():
    chosen: dict[tuple, tuple[Path, list]] = {}
    for p in files:                       # later files overwrite whole curves
        per: dict[tuple, list] = defaultdict(list)
        for line, r, conv, why in curve_rows(p):
            if conv is None:
                qraw(p, line, why, r); continue
            per[(conv["hashtag"], conv["region"], conv["period"])].append((line, r, conv))
        for key, pts in per.items():
            if key in chosen:
                old_p, old_pts = chosen[key]
                for line, r, _ in old_pts:
                    qraw(old_p, line, "earlier_same_day_curve_capture(later capture used whole)", r)
            chosen[key] = (p, pts)
    out = []
    for key in sorted(chosen):
        p, pts = chosen[key]
        curve_src[(day,) + key] = p.name
        bydate: dict[str, list] = defaultdict(list)
        for line, r, conv in pts:
            bydate[conv["date"]].append((line, r, conv))
        for d in sorted(bydate):
            vals = {c["value"] for _, _, c in bydate[d]}
            if len(vals) > 1:
                for line, r, _ in bydate[d]:
                    qraw(p, line, "conflicting_readings_same_capture", r)
                continue
            out.append(bydate[d][0][2])
    if len(files) > 1:
        superseded.append(f"{', '.join(f.name for f in files[:-1])} (cc curves {day}: per-curve, later capture wins)")
    write_csv(layout.raw_dir(date.fromisoformat(day)) / "cc-curves.csv",
              ["hashtag", "region", "period", "date", "value", "detail_id"], out)
    counts["raw"][f"{day}/cc-curves.csv"] = len(out)

# ---------- old tracker ----------
old = rows(args.old_tracker)
old_cols = list(old[0].keys())
VERDICT = {"做": "make", "观望": "watch", "不做": "skip"}
METRIC_EQ = {"none_daily_volume": "none"}
DIMS = {"heat": "score_heat", "trend": "score_trend", "share": "score_share",
        "competition": "score_competition", "window": "score_window"}
quar_tr, accepted = [], []
seen = Counter((r["date"], r["canonical_id"]) for r in old)
for r in old:
    reason = []
    rid = kebab(r["canonical_id"])
    if seen[(r["date"], r["canonical_id"])] > 1:
        reason.append("duplicate (date, canonical_id) in old tracker")
    if rid not in registry:
        reason.append(f"unmapped meme: {rid} not in data/memes.csv")
    else:
        m = registry[rid]
        names = {m.name, m.id, *m.aliases, *("#" + t for t in m.cc_hashtags)}
        if r["meme"].strip() not in names:
            reason.append(f"name evidence mismatch: '{r['meme']}' not registry name/alias/#tag of {rid}")
        om = METRIC_EQ.get(r["primary_heat_metric"], r["primary_heat_metric"])
        if om != m.primary_metric:
            reason.append(f"metric basis mismatch: old {r['primary_heat_metric']} vs registry {m.primary_metric}")
        elif om == "cc_index_30d":
            if norm_hashtag(r["cc_tag"]) != m.cc_hashtags[0] or r["cc_region"] != m.primary_region:
                reason.append(f"cc basis mismatch: old #{r['cc_tag']} {r['cc_region']} vs registry "
                              f"#{m.cc_hashtags[0]} {m.primary_region}")
    if r["verdict"] not in VERDICT:
        reason.append(f"unknown verdict {r['verdict']!r}")
    try:
        sc = {k: int(r[v]) for k, v in DIMS.items()}
        if sum(sc.values()) != int(r["score"]):
            reason.append(f"score sum {sum(sc.values())} != score {r['score']}")
    except ValueError:
        reason.append("missing or non-integer score")
    if r["part"] not in ("main", "early"):
        reason.append(f"unknown part {r['part']!r}")
    if reason:
        quar_tr.append({**r, "reason": " | ".join(reason)})
        evidence.setdefault(r["meme"], ("", "tracker row quarantined"))
    else:
        accepted.append((r, rid, sc))
        evidence[r["meme"]] = (rid, f"tracker canonical_id {r['canonical_id']} -> {rid} and meme name matches registry")

report_days = sorted({r["date"] for r, _, _ in accepted})
# ---------- CC top100 + remixes for report days ----------
for day in report_days:
    d = date.fromisoformat(day)
    p = CC / f"{day}_NewsEnt_top100_all.csv"
    if p.is_file():
        out = [{"hashtag": r["hashtag"], "region": r["region"], "period": r["period_days"], "rank": r["rank"],
                "rank_change": r["rank_change"], "posts": r["posts"], "views": r["views"],
                "industry": r["industry"], "detail_id": r["detail_id"]} for r in rows(p)]
        write_csv(layout.raw_dir(d) / "cc-top100.csv",
                  ["hashtag", "region", "period", "rank", "rank_change", "posts", "views", "industry", "detail_id"], out)
        counts["raw"][f"{day}/cc-top100.csv"] = len(out)
    rfiles = captures(f"remix_stats_{day}*.csv").get(day, [])
    if rfiles:
        use = rfiles[-1]
        superseded += [f"{f.name} (remixes {day}: superseded by {use.name})" for f in rfiles[:-1]]
        out = []
        for line, r in enumerate(rows(use), start=2):
            mid, _ = map_name(r["meme"])
            if not mid:
                qraw(use, line, "unmapped_meme", r); continue
            if r.get("is_original", "") == "yes":
                qraw(use, line, "original_not_remix", r); continue
            if r.get("in_top_sample") != "yes":
                qraw(use, line, "not_in_old_top_sample", r); continue
            if not r["views"].strip():
                qraw(use, line, "no_views_reading", r); continue
            out.append({"meme_id": mid, "link": r["link"], "platform": r["platform"], "creator": r["creator"],
                        "posted_on": r["date"], "views": r["views"], "likes": r["likes"], "shares": r["shares"],
                        "comments": r["comments"], "saves": r["saves"], "is_ai": r["is_AI"] or "unclear"})
        write_csv(layout.raw_dir(d) / "remixes.csv",
                  ["meme_id", "link", "platform", "creator", "posted_on", "views", "likes", "shares",
                   "comments", "saves", "is_ai"], out)
        counts["raw"][f"{day}/remixes.csv"] = len(out)

    det_p = L / f"cc_hashtag_detail_{day}.json"
    if det_p.is_file():
        inputs.append(det_p)
        det = json.loads(det_p.read_text(encoding="utf-8") or "{}")
        aud = []
        for tag, dd in (det.items() if isinstance(det, dict) else []):
            if tag.startswith("_") or not isinstance(dd, dict):
                continue
            for per, pp in (dd.get("periods") or {}).items():
                if not isinstance(pp, dict):
                    qraw(det_p, 0, "cc_detail_period_without_data", {"tag": tag, "period": per, "value": pp}); continue
                for b, v in sorted((pp.get("audience_age_pct") or {}).items()):
                    aud.append({"hashtag": norm_hashtag(tag), "region": dd["region"], "period": per,
                                "dimension": "age", "bucket": b, "value": v, "unit": "pct"})
                for x in pp.get("audience_top_regions_popularity_index") or []:
                    aud.append({"hashtag": norm_hashtag(tag), "region": dd["region"], "period": per,
                                "dimension": "country", "bucket": x["region"], "value": x["index"], "unit": "index"})
        if aud:
            write_csv(layout.raw_dir(d) / "cc-audience.csv",
                      ["hashtag", "region", "period", "dimension", "bucket", "value", "unit"], aud)
            counts["raw"][f"{day}/cc-audience.csv"] = len(aud)
    gaps = []
    packs = captures(f"meme_pack_{day}*.json").get(day, [])
    if packs:
        gaps += [{"source": packs[-1].name, "note": g} for g in json.loads(packs[-1].read_text(encoding="utf-8")).get("gaps") or []]
    wp = L / f"watchlist_posts_{day}.csv"
    if wp.is_file():
        out = []
        for line, r in enumerate(rows(wp), start=2):
            if not r["post_url"].strip():
                gaps.append({"source": f"watchlist {r['platform']}@{r['handle']}", "note": r["note"]}); continue
            mid = ""
            if r["meme"].strip():
                mid, _ = map_name(r["meme"])
                if not mid:
                    qraw(wp, line, "watchlist_meme_unmapped(row kept, meme_id empty)", r); mid = ""
            ft = r["format_type"].lower()
            out.append({"platform": r["platform"], "handle": r["handle"], "link": r["post_url"],
                        "posted_on": r["post_date"][:10], "caption": r["caption"], "views": r["views"],
                        "likes": r["likes"], "meme_id": mid,
                        "is_template": "true" if "template" in ft else "false",
                        "is_ai_effect": "true" if re.search(r"\bai\b", ft) else "false"})
        write_csv(layout.raw_dir(d) / "watchlist-posts.csv",
                  ["platform", "handle", "link", "posted_on", "caption", "views", "likes", "meme_id",
                   "is_template", "is_ai_effect"], out)
        counts["raw"][f"{day}/watchlist-posts.csv"] = len(out)
    if gaps:
        (layout.raw_dir(d) / "gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        counts["raw"][f"{day}/gaps.json"] = len(gaps)

# ---------- new tracker rows, computed by radar code ----------
ISO_LEAD = re.compile(r"^(\d{4}-\d{2}-\d{2})(?![\d])")
new_rows, tr_ev = [], []
for r, rid, sc in sorted(accepted, key=lambda x: (x[0]["date"], x[1])):
    d = date.fromisoformat(r["date"])
    raw = load_day(layout, d, registry)
    hist = load_history(layout, d)
    m = ISO_LEAD.match(r["ignite_date"].strip())
    j = MemeJudgment(meme_id=rid, part=r["part"], verdict=VERDICT[r["verdict"]], reason="migrated",
                     scores={k: {"score": v} for k, v in sc.items()},
                     ignite_date=m.group(1) if m else None)
    prev = tracker.previous(new_rows, rid, d)
    f = finish_facts(compute_facts(registry[rid], raw, hist, prev), j, d)
    row = _tracker_row(d, PackMeme(judgment=j, facts=f))
    new_rows.append(row)
    meme = registry[rid]
    cap = ""
    if meme.primary_metric == "cc_index_30d" and f.primary_date:
        caps = hist.curve_captures(meme.cc_hashtags[0], meme.primary_region, 30)
        cap = caps[0].isoformat() if caps else ""
        cap += " (" + curve_src.get((cap, meme.cc_hashtags[0], meme.primary_region, "30"), "?") + ")"
    tr_ev.append({
        "date": r["date"], "meme_id": rid, "old_canonical_id": r["canonical_id"], "old_meme": r["meme"],
        "primary_metric": meme.primary_metric,
        "basis": (f"cc #{meme.cc_hashtags[0]} {meme.primary_region} 30d" if meme.primary_metric == "cc_index_30d"
                  else meme.primary_metric),
        "cc_capture_day": cap,
        "old_primary_value": r["primary_heat_value"], "old_primary_date": r["primary_heat_date"],
        "new_primary_value": row["primary_value"], "new_primary_date": row["primary_date"],
        "primary_status": ("no raw reading -> empty" if not row["primary_value"] and meme.primary_metric != "none"
                           else "none metric" if meme.primary_metric == "none"
                           else "same as old" if (row["primary_value"], row["primary_date"]) ==
                           (f"{float(r['primary_heat_value']):g}" if r["primary_heat_value"] else "", r["primary_heat_date"])
                           else "recomputed differs from old"),
        "old_ignite_text": r["ignite_date"], "ignite_date_used": row["ignite_date"],
        "old_days_hot": r["days_hot"], "new_days_hot": row["days_hot"],
        "old_remix_n": r["remix_n"], "new_share_n": row["share_n"],
    })
existing = {(x["date"], x["meme_id"]): x for x in tracker.load(layout.tracker)}
merged = dict(existing)
kept_existing = 0
for row in new_rows:
    k = (row["date"], row["meme_id"])
    norm = {c: "" if row.get(c) is None else str(row.get(c)) for c in tracker.COLUMNS}
    if k in existing:
        if {c: existing[k].get(c, "") for c in tracker.COLUMNS} != norm:
            kept_existing += 1
            src = next(r for r, rid, _ in accepted if (r["date"], rid) == k)
            quar_tr.append({**src, "reason": "existing data/tracker.csv row for (date, meme_id) kept; migrated row differs"})
        continue
    merged[k] = norm
write_rows(layout.tracker, tracker.COLUMNS, [merged[k] for k in sorted(merged)])

# ---------- backtest with the new code ----------
as_of = args.as_of or max(date.fromisoformat(x["date"]) for x in new_rows)
trows = tracker.load(layout.tracker)
evals, summary = backtest.evaluate(trows, registry, load_history(layout, as_of), as_of)
backtest.write(evals, summary, layout.backtest_json, layout.backtest_csv)

# ---------- side files ----------
write_csv(OUT / "quarantine-tracker.csv", old_cols + ["reason"], quar_tr)
quar_raw.sort(key=lambda q: (q["source_file"], int(q["source_line"]), q["reason"]))
write_csv(OUT / "quarantine-raw.csv", ["source_file", "source_line", "reason", "original"], quar_raw)
write_csv(OUT / "mapping-evidence.csv", ["name", "meme_id", "evidence"],
          [{"name": k, "meme_id": v[0], "evidence": v[1]} for k, v in sorted(evidence.items())])
write_csv(OUT / "tracker-evidence.csv", list(tr_ev[0].keys()) if tr_ev else ["date"], tr_ev)
uniq_inputs = sorted({str(p) for p in inputs + [args.old_tracker]})
manifest = {
    "as_of": as_of.isoformat(),
    "inputs_sha256": {p: sha(Path(p)) for p in uniq_inputs},
    "superseded_files": sorted(set(superseded)),
    "not_used": ["heat_*.json (JSON twins of heat CSVs)", "cc_hashtag_trends_*_merged.csv (mixes captures)",
                 "history/backtest_latest.* (old conclusions, reference only)"],
    "counts": {
        "old_tracker_by_date": dict(sorted(Counter(r["date"] for r in old).items())),
        "migrated_rows_by_date": dict(sorted(Counter(r["date"] for r in new_rows).items())),
        "tracker_by_date_after_merge": dict(sorted(Counter(k[0] for k in merged).items())),
        "existing_rows_kept_over_migrated": kept_existing,
        "quarantine_tracker": len(quar_tr),
        "quarantine_tracker_by_reason": dict(sorted(Counter(
            re.sub(r":.*", "", x) for q in quar_tr for x in q["reason"].split(" | ")).items())),
        "quarantine_raw": len(quar_raw),
        "quarantine_raw_by_reason": dict(sorted(Counter(q["reason"] for q in quar_raw).items())),
        "raw_written": dict(sorted(counts["raw"].items())),
        "backtest": dict(sorted(Counter(f"{e.verdict}:{e.result}" for e in evals).items())),
        "backtest_summary": summary.text_zh(),
    },
}
(OUT / "migration-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
print(json.dumps(manifest["counts"], ensure_ascii=False, indent=1))
