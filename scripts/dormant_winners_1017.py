"""Dormant winners (read-only, 17 Oct): which old / recently-stopped creatives deserve a relaunch.

Operator: 看看 register list & paid student list & ads manager，建议我哪些封尘很久的广告 /
最近关掉的新跑的广告，可以建起来. Per creative (ad name folded by cpa.ad_key, SG campaigns only):
  · Paid Student List: SG sales all-time / 180d / 90d / 30d, last sale date
  · Register list (any tab whose title contains regist/报名/報名): registrations all-time / 90d
  · Meta, SG old + HK: lifetime, 90d and 14d spend + registrations, last 7 delivering days
    before it stopped (rule 3), newest ad's post id and status
A candidate = has SG sales, spent < RM20 in the last 14 days. Ranked by sales then CPA.
No writes.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCOUNTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _sg(c: str) -> bool:
    c = cpa.norm(c)
    return "[sg]" in c or "martin-sg" in c or "martin sg" in c


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    D = {w: today - dt.timedelta(days=w) for w in (14, 30, 90, 180)}

    sh = SheetsClient(s.secrets.google_sa_json)
    meta = sh._svc.spreadsheets().get(spreadsheetId=s.cpa.spreadsheet_id, fields="sheets.properties.title").execute()
    titles = [x["properties"]["title"] for x in meta.get("sheets", [])]
    log.info("成交表 workbook 的 tab：%s", titles)

    # ── paid ──
    sales, _c, _h = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), s.cpa.price_myr)
    paid: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"all": 0, 180: 0, 90: 0, 30: 0, "last": None, "names": set()})
    for x in sales:
        if not x.date or not _sg(x.campaign):
            continue
        p = paid[cpa.ad_key(x.ad)]
        p["all"] += 1
        p["names"].add(x.ad[:40])
        p["last"] = max(p["last"], x.date) if p["last"] else x.date
        for w in (180, 90, 30):
            if x.date >= D[w]:
                p[w] += 1
    log.info("成交表：SG 单 %d 笔，对应 %d 支片", sum(v["all"] for v in paid.values()), len(paid))

    # ── registrations ──
    reg: Dict[str, Dict[str, int]] = defaultdict(lambda: {"all": 0, 90: 0})
    for t in titles:
        tl = t.lower()
        if not ("regist" in tl or "报名" in t or "報名" in t):
            continue
        vals = sh.read_tab(s.cpa.spreadsheet_id, t)
        try:
            rows, _c2, _h2 = cpa.parse_sales(vals, 0.0)
        except Exception as exc:  # noqa: BLE001
            log.info("注册 tab %r 读不了：%s · 表头 %s", t, exc, (vals[:1] or [[]])[0][:12])
            continue
        n = 0
        for x in rows:
            if not _sg(x.campaign):
                continue
            r = reg[cpa.ad_key(x.ad)]
            r["all"] += 1
            n += 1
            if x.date and x.date >= D[90]:
                r[90] += 1
        log.info("注册 tab %r：%d 行 · SG 带 UTM 的 %d 行", t, len(vals), n)

    # ── Meta ──
    def pull(window: Dict[str, Any]) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0])
        for _, acct in ACCOUNTS:
            for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_name,spend,actions", **window}):
                o = out[cpa.ad_key(r.get("ad_name") or "")]
                o[0] += _f(r.get("spend"))
                o[1] += extract_results(r.get("actions"), tok)
        return out

    def tr(since: dt.date) -> Dict[str, str]:
        return {"time_range": json.dumps({"since": since.isoformat(), "until": today.isoformat()})}

    life, m90, m14 = pull({"date_preset": "maximum"}), pull(tr(D[90])), pull(tr(D[14]))
    newest: Dict[str, Dict[str, Any]] = {}
    for label, acct in ACCOUNTS:
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,effective_status,created_time,creative{effective_object_story_id}",
                                            "limit": 500}):
            k = cpa.ad_key(a.get("name") or "")
            if k not in paid:
                continue
            if (a.get("created_time") or "") > (newest.get(k, {}).get("created_time") or ""):
                newest[k] = {**a, "acct": label}

    # weekly lead history for candidates (rule 3: last 7 delivering days before it stopped)
    weekly: Dict[str, List[tuple]] = defaultdict(list)
    for _, acct in ACCOUNTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_name,spend,actions",
                                                 "time_increment": 7, **tr(D[180])}):
            k = cpa.ad_key(r.get("ad_name") or "")
            if k in paid:
                weekly[k].append((r.get("date_start"), _f(r.get("spend")), extract_results(r.get("actions"), tok)))

    rows = []
    for k, p in paid.items():
        if m14[k][0] >= 20:
            continue
        sp, ld = life[k]
        rows.append((p[90], p["all"], -(sp / p["all"]) if p["all"] else 0, k))
    log.info("═" * 120)
    log.info("候选：有 SG 成交、最近 14 天花费 < RM20 · 排序：90 天单数 → 全史单数 → 全史 CPA")
    for n90, nall, _, k in sorted(rows, reverse=True):
        p, sp, ld = paid[k], life[k][0], life[k][1]
        wk: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0])
        for d0, a, b in weekly[k]:
            wk[d0][0] += a
            wk[d0][1] += b
        live = sorted((d0, v) for d0, v in wk.items() if v[0] >= 5)
        lastwk = live[-1] if live else None
        nw = newest.get(k, {})
        log.info("▌%-40s 全史 %d单 · 180d %d · 90d %d · 30d %d · 最近成交 %s", sorted(p["names"])[0], p["all"], p[180], p[90],
                 p[30], p["last"])
        log.info("    Meta 全史 RM%.0f · %d lead · CPL %s · 全史 CPA %s · lead 变买家 %s · 注册名单 %d（90d %d）",
                 sp, int(ld), f"{sp / ld:,.0f}" if ld else "—", f"RM{sp / p['all']:,.0f}" if p["all"] and sp else "—",
                 f"{p['all'] / ld * 100:.0f}%" if ld else "—", reg[k]["all"], reg[k][90])
        log.info("    90d RM%.0f · %d lead · 14d RM%.0f · 最后一周有投放 %s：RM%.0f · %d lead",
                 m90[k][0], int(m90[k][1]), m14[k][0], lastwk[0] if lastwk else "180 天内没有",
                 lastwk[1][0] if lastwk else 0, int(lastwk[1][1]) if lastwk else 0)
        log.info("    最新广告 %s %s %s · 建 %s · post %s", nw.get("acct"), nw.get("id"), nw.get("effective_status"),
                 (nw.get("created_time") or "")[:10], (nw.get("creative") or {}).get("effective_object_story_id"))
    final_summary(log, f"dormant winners · {len(rows)} candidates")


if __name__ == "__main__":
    main()
