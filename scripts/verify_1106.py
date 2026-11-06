"""Full cross-checked readout of the live SG ads, CPA and CPL (read-only, 6 Nov).

Operator: 全部查完。再三确保数据资料全部准确，全部 CPA CPL 准确的情况下，才给我最精准的回报。
Window W = ADBOT_SINCE (default Thursday 2026-11-05) to today (SGT). Checks, each printed:
  1. Spend reconciliation: account-level spend/registrations per day == sum of every ad's per day.
  2. Registrations: Meta (offsite_conversion.fb_pixel_complete_registration) per day vs Register tab
     SG rows per day, and per live ad (UTM campaign + ad set + ad, and ad name only).
  3. Per live ad (ad, ad set and campaign all ACTIVE): W spend / registrations / impressions / link
     clicks / CTR / CPM / click-to-registration, per day; 60 days; lifetime; CPL in each window.
  4. Own sales (paid sheet, UTM campaign + ad set + ad) with dates; every same-named copy on SG old +
     HK; for each sale whether a copy also spent in the 14 days before it (shared -> not counted as
     clean); lifetime CPA, next-sale CPA, band.
  5. Rule 3: the 7 days ending on the last day it spent before W (registrations then).
  6. Rule 4: the same ad name on SG old + HK (any campaign) and on MY (read only): lifetime spend /
     registrations and sales of that name in the paid sheet.
No names, phones or emails are printed. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.graph import TransientGraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY = "act_1011719073600566"
WINDOW = 14


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _sg(c):
    c = cpa.norm(c)
    return "[sg]" in c or "martin-sg" in c or "martin sg" in c


def _my(c):
    c = cpa.norm(c)
    return "[my]" in c or "martin-my" in c or "martin my" in c


def _cpl(sp, rg):
    return f"RM{sp / rg:.2f}" if rg else "—（0 报名）"


def band(v, c):
    if v is None:
        return "零成交"
    if v <= c.target_myr:
        return "≤目标 740"
    if v <= c.healthy_max_myr:
        return "健康 ≤860"
    if v <= c.max_acceptable_myr:
        return "可接受 ≤1,040"
    if v <= c.hard_stop_myr:
        return "暂停候选 ≤1,300"
    return "超硬停线 1,300"


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    w0 = dt.date.fromisoformat(os.environ.get("ADBOT_SINCE") or "2026-11-05")
    d60 = today - dt.timedelta(days=60)
    log.info("读数时间 %s SGT · 窗口 W = %s ~ %s（今天未完）· 事件 %s", (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
             w0, today, tok)

    def tr(a, b):
        return json.dumps({"since": a.isoformat(), "until": b.isoformat()})

    def ins(acct, ids, **p):                                     # ad-level, filtered to ids, chunks of 50 ids
        out = []
        for i in range(0, len(ids), 50):
            out += g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, **p,
                                                   "filtering": json.dumps([{"field": "ad.id", "operator": "IN",
                                                                             "value": ids[i:i + 50]}])})
        return out

    # ── sheets ──────────────────────────────────────────────────────────────────────────────────
    sh = SheetsClient(s.secrets.google_sa_json)
    sales, _c, _h = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), s.cpa.price_myr)
    sale_by_key = defaultdict(list)
    sg_name, my_name = Counter(), Counter()
    for x in sales:
        sale_by_key[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))].append(x)
        if _sg(x.campaign):
            sg_name[cpa.ad_key(x.ad)] += 1
        elif _my(x.campaign):
            my_name[cpa.ad_key(x.ad)] += 1
    sales_w = [x for x in sales if x.date and x.date >= w0]
    log.info("成交表 %r：%d 行 · W 内成交 %d 笔（SG %d）", s.cpa.sales_tab, len(sales), len(sales_w),
             sum(1 for x in sales_w if _sg(x.campaign)))

    meta = sh._svc.spreadsheets().get(spreadsheetId=s.cpa.spreadsheet_id, fields="sheets.properties.title").execute()
    reg_day, reg_key, reg_name, reg_latest = Counter(), Counter(), Counter(), None
    for t in (x["properties"]["title"] for x in meta.get("sheets", [])):
        if not ("regist" in t.lower() or "报名" in t or "報名" in t):
            continue
        rows, _c2, _h2 = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, t), 0.0)
        sg = [x for x in rows if _sg(x.campaign)]
        dated = [x.date for x in sg if x.date]
        if dated:
            reg_latest = max(dated + ([reg_latest] if reg_latest else []))
        log.info("报名表分页 %r：SG 带 UTM 的 %d 行 · 最近一行日期 %s", t, len(sg), max(dated, default=None))
        for x in sg:
            if x.date and x.date >= w0:
                reg_day[x.date] += 1
                reg_key[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))] += 1
                reg_name[cpa.ad_key(x.ad)] += 1

    # ── every ad on SG old + HK (for copies + same-name) ────────────────────────────────────────
    all_ads, by_name, live = defaultdict(list), defaultdict(list), []
    for label, acct in ACCTS:
        for a in g._get_all(f"{acct}/ads", {"limit": 500, "fields": "id,name,effective_status,created_time,"
                                            "campaign{id,name,effective_status,daily_budget},"
                                            "adset{id,name,effective_status,daily_budget}"}):
            c, st = a.get("campaign") or {}, a.get("adset") or {}
            k = (cpa.ad_key(c.get("name") or ""), cpa.ad_key(st.get("name") or ""), cpa.ad_key(a.get("name") or ""))
            all_ads[k].append((label, acct, a))
            by_name[cpa.ad_key(a.get("name") or "")].append((label, acct, a))
            if (a.get("effective_status") == "ACTIVE" and c.get("effective_status") == "ACTIVE"
                    and st.get("effective_status") == "ACTIVE"):
                live.append((label, acct, a, k))
    log.info("在跑（ad + ad set + campaign 都 ACTIVE）：%d 支", len(live))

    # ── 1 + 2: reconciliation per account per day ───────────────────────────────────────────────
    log.info("═" * 100)
    w_ad = {}                                                    # ad_id -> W row totals
    for label, acct in ACCTS:
        acc = {r["date_start"]: (_f(r.get("spend")), extract_results(r.get("actions"), tok))
               for r in g._get_all(f"{acct}/insights", {"time_increment": 1, "fields": "spend,actions",
                                                        "time_range": tr(w0, today)})}
        rows = g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_increment": 1,
                                               "fields": "ad_id,ad_name,campaign_name,spend,actions,impressions,"
                                                         "inline_link_clicks",
                                               "time_range": tr(w0, today)})
        per_day = defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            sp, rg = _f(r.get("spend")), extract_results(r.get("actions"), tok)
            per_day[r["date_start"]][0] += sp
            per_day[r["date_start"]][1] += rg
            t = w_ad.setdefault(r["ad_id"], {"label": label, "name": r.get("ad_name") or "", "camp": r.get("campaign_name") or "",
                                             "sp": 0.0, "rg": 0.0, "imp": 0.0, "clk": 0.0, "days": {}})
            t["sp"] += sp
            t["rg"] += rg
            t["imp"] += _f(r.get("impressions"))
            t["clk"] += _f(r.get("inline_link_clicks"))
            t["days"][r["date_start"]] = (sp, rg)
        for d in sorted(set(acc) | set(per_day)):
            a_sp, a_rg = acc.get(d, (0.0, 0.0))
            s_sp, s_rg = per_day.get(d, (0.0, 0.0))
            ok = "✓ 对得上" if abs(a_sp - s_sp) < 0.02 and a_rg == s_rg else "✗ 对不上"
            log.info("核对 %s %s · 账户层 花 RM%.2f 报名 %d · 各广告相加 花 RM%.2f 报名 %d · %s", label, d, a_sp, a_rg,
                     s_sp, s_rg, ok)
        tsp, trg = sum(v[0] for v in acc.values()), sum(v[1] for v in acc.values())
        log.info("▌%s W 合计 花 RM%.2f 报名 %d · CPL %s", label, tsp, trg, _cpl(tsp, trg))
    log.info("W 内有花钱的每一支广告（含已关的）：")
    for aid, t in sorted(w_ad.items(), key=lambda kv: -kv[1]["sp"]):
        if t["sp"] > 0:
            st = next((a.get("effective_status") for _l, _a, a, _k in live if a["id"] == aid), None) or \
                 g.get_object(aid, "effective_status").get("effective_status")
            log.info("   %s ad %s %r · 现在 %s · 花 RM%.2f 报名 %d · %s", t["label"], aid, t["name"][:40], st, t["sp"],
                     t["rg"], " · ".join(f"{d[5:]} RM{v[0]:.2f}/{v[1]:.0f}" for d, v in sorted(t["days"].items())))

    log.info("═" * 100)
    meta_day = Counter()
    for t in w_ad.values():
        for d, v in t["days"].items():
            meta_day[d] += v[1]
    log.info("报名核对（Meta 像素 vs 报名表 SG 行）· 报名表最近一行 %s", reg_latest)
    d = w0
    while d <= today:
        log.info("   %s Meta %d · 报名表 %d", d, meta_day[d.isoformat()], reg_day[d])
        d += dt.timedelta(days=1)

    # ── 3-6: per live ad ────────────────────────────────────────────────────────────────────────
    by_acct = defaultdict(list)
    for label, acct, a, k in live:
        by_acct[acct].append(a["id"])
    life, s60, daily60 = {}, {}, defaultdict(dict)
    for acct, ids in by_acct.items():
        for r in ins(acct, ids, fields="ad_id,spend,actions", date_preset="maximum"):
            life[r["ad_id"]] = (_f(r.get("spend")), extract_results(r.get("actions"), tok))
        a = d60
        while a <= today:                                        # 30-day chunks, per day
            b = min(a + dt.timedelta(days=29), today)
            for r in ins(acct, ids, fields="ad_id,spend,actions", time_increment=1, time_range=tr(a, b)):
                daily60[r["ad_id"]][r["date_start"]] = (_f(r.get("spend")), extract_results(r.get("actions"), tok))
            a = b + dt.timedelta(days=1)
    for aid, days in daily60.items():
        s60[aid] = (sum(v[0] for v in days.values()), sum(v[1] for v in days.values()))

    # same name lifetime, SG old + HK (any campaign) and MY
    name_life = defaultdict(lambda: [0.0, 0.0, 0])
    want = {cpa.ad_key(a.get("name") or "") for _l, _ac, a, _k in live}
    for label, acct in ACCTS:
        ids = [a["id"] for n in want for (_l, ac, a) in by_name.get(n, []) if ac == acct]
        for r in ins(acct, ids, fields="ad_id,ad_name,spend,actions", date_preset="maximum"):
            n = cpa.ad_key(r.get("ad_name") or "")
            name_life[n][0] += _f(r.get("spend"))
            name_life[n][1] += extract_results(r.get("actions"), tok)
            name_life[n][2] += 1
    my_life = defaultdict(lambda: [0.0, 0.0, 0])
    my_err = ""
    try:
        my_ids = [a["id"] for a in g._get_all(f"{MY}/ads", {"fields": "id,name", "limit": 500})
                  if cpa.ad_key(a.get("name") or "") in want]
        for r in ins(MY, my_ids, fields="ad_id,ad_name,spend,actions", date_preset="maximum"):
            n = cpa.ad_key(r.get("ad_name") or "")
            my_life[n][0] += _f(r.get("spend"))
            my_life[n][1] += extract_results(r.get("actions"), tok)
            my_life[n][2] += 1
    except TransientGraphError:
        raise
    except Exception as exc:                                     # MY read is a bonus; never block the readout
        my_err = str(exc)[:160]

    cfg = s.cpa
    summary = []
    for label, acct, a, k in live:
        aid, name = a["id"], a.get("name") or ""
        c, st = a.get("campaign") or {}, a.get("adset") or {}
        w = w_ad.get(aid, {"sp": 0.0, "rg": 0.0, "imp": 0.0, "clk": 0.0, "days": {}})
        lsp, lrg = life.get(aid, (0.0, 0.0))
        sp60, rg60 = s60.get(aid, (0.0, 0.0))
        log.info("═" * 100)
        log.info("▌%s ad %s %r · 建于 %s", label, aid, name, (a.get("created_time") or "")[:10])
        log.info("  campaign %s %r（日预算 %s）· ad set %s %r（日预算 %s）", c.get("id"), c.get("name"),
                 f"RM{_f(c.get('daily_budget')) / 100:.0f}" if c.get("daily_budget") else "—", st.get("id"), st.get("name"),
                 f"RM{_f(st.get('daily_budget')) / 100:.0f}" if st.get("daily_budget") else "—")
        log.info("  W：花 RM%.2f · 报名（Meta）%d · CPL %s · 曝光 %d · 链接点击 %d · CTR %s · CPM %s · 点击→报名 %s · 每天 %s",
                 w["sp"], w["rg"], _cpl(w["sp"], w["rg"]), w["imp"], w["clk"],
                 f"{w['clk'] / w['imp'] * 100:.2f}%" if w["imp"] else "—",
                 f"RM{w['sp'] / w['imp'] * 1000:.2f}" if w["imp"] else "—",
                 f"{w['rg'] / w['clk'] * 100:.1f}%" if w["clk"] else "—",
                 " · ".join(f"{d[5:]} RM{v[0]:.2f}/{v[1]:.0f}" for d, v in sorted(w["days"].items())))
        log.info("  W 报名表：三个 UTM 都对上 %d · 只对 ad 名 %d", reg_key.get(k, 0), reg_name.get(k[2], 0))
        log.info("  60 天（%s 起）：花 RM%.2f 报名 %d CPL %s · 全期：花 RM%.2f 报名 %d CPL %s", d60, sp60, rg60, _cpl(sp60, rg60),
                 lsp, lrg, _cpl(lsp, lrg))
        prior = sorted(d for d, v in daily60.get(aid, {}).items() if d < w0.isoformat() and v[0] > 0)
        if prior:
            last = dt.date.fromisoformat(prior[-1])
            seg = [v for d, v in daily60[aid].items() if (last - dt.timedelta(days=6)).isoformat() <= d <= prior[-1]]
            log.info("  规矩 3：W 之前最后花钱的一天 %s · 那 7 天（%s~%s）花 RM%.2f 报名 %d · 60 天里有花钱的日子 %d 天",
                     last, last - dt.timedelta(days=6), last, sum(v[0] for v in seg), sum(v[1] for v in seg), len(prior))
        else:
            log.info("  规矩 3：60 天内 W 之前没有花钱的日子")

        sold = sorted(sale_by_key.get(k, []), key=lambda x: x.date or dt.date.min)
        twins = all_ads[k]
        log.info("  自己的成交 %d 笔 · 同 campaign + ad set + ad 名字的广告 %d 支：%s", len(sold), len(twins),
                 [f"{t[0]} {t[2]['id']} {t[2].get('effective_status')}" for t in twins])
        verdict = Counter()
        for x in sold:
            if len(twins) == 1:
                verdict["本广告"] += 1
                log.info("    成交 %s · 只有这一支同名 → 本广告", x.date)
                continue
            if not x.date:
                verdict["没日期"] += 1
                log.info("    成交（没有日期）· 有同名副本 → 判断不了")
                continue
            delivered = []
            for t_label, t_acct, t in twins:
                r = (g._get_all(f"{t['id']}/insights", {"fields": "spend,actions",
                                                        "time_range": tr(x.date - dt.timedelta(days=WINDOW), x.date)}) or [{}])[0]
                if _f(r.get("spend")) > 0:
                    delivered.append((t_label, t["id"], _f(r.get("spend")), extract_results(r.get("actions"), tok)))
            mine = any(dd[1] == aid for dd in delivered)
            v = "本广告" if mine and len(delivered) == 1 else "共用" if mine else "不是它"
            verdict[v] += 1
            log.info("    成交 %s · 前 %d 天有花钱的同名：%s → %s", x.date, WINDOW,
                     [f"{dd[0]} {dd[1]} RM{dd[2]:.2f}/{dd[3]:.0f}" for dd in delivered] or "没有", v)
        clean = verdict["本广告"]
        cpa_all = lsp / len(sold) if sold else None
        cpa_clean = lsp / clean if clean else None
        nxt = lsp / (len(sold) + 1)
        log.info("  CPA：全期花 RM%.2f ÷ 自己成交 %d = %s（%s）· 只算干净的 %d 笔 = %s（%s）· 下一单现在来 = RM%.2f（%s）",
                 lsp, len(sold), f"RM{cpa_all:.2f}" if cpa_all else "—", band(cpa_all, cfg), clean,
                 f"RM{cpa_clean:.2f}" if cpa_clean else "—", band(cpa_clean, cfg), nxt, band(nxt, cfg))
        n = k[2]
        nl, ml = name_life[n], my_life[n]
        log.info("  规矩 4 同名片：SG老户 + HK %d 支 全期花 RM%.2f 报名 %d · SG 成交表 %d 笔 · MY %d 支 全期花 RM%.2f 报名 %d · MY 成交表 %d 笔%s",
                 nl[2], nl[0], nl[1], sg_name[n], ml[2], ml[0], ml[1], my_name[n], f" · MY 读不到：{my_err}" if my_err else "")
        summary.append(f"{label} {aid} W RM{w['sp']:.2f}/{w['rg']:.0f} · 60天 RM{sp60:.2f}/{rg60:.0f} · CPA "
                       f"{f'RM{cpa_all:.0f}' if cpa_all else '—'}（干净 {clean}/{len(sold)}）")
    final_summary(log, " | ".join(summary))


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
