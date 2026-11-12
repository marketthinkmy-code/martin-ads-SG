"""11月新片7支 since launch, every audience (read-only, 12 Nov).

Operator 12 Nov: 「Family and Relationships | 11月新片7支 好像很贵，你现在破例不要看周四窗口归零，而是看新视频从开始
跑，到现在。分析了，告诉我怎么做决定。」 For the 21 ads (7 videos × Food and Drink + Milk 120259458979710093 /
Family and Relationships 120259499514770093 / Health & Wellness 120259499592070093, SG老户), lifetime
(date_preset maximum): spend, impressions, CPM, link clicks, CTR, CPC, landing-page views, Meta registrations,
Register-tab rows (UTM campaign + ad set + ad, any date), CPL, LP view → registration rate; status. Then
per campaign and per video totals, and per-day spend / registrations for each campaign. No writes.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCT = "act_1024930575770087"
CAMPS = {"120259458979710093": "Food and Drink + Milk", "120259499514770093": "Family and Relationships",
         "120259499592070093": "Health & Wellness"}


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def act(actions, t):
    return sum(_f(a.get("value")) for a in actions or [] if a.get("action_type") == t)


def vid(name):
    n = cpa.ad_key(name)
    for k in "1235678":
        if n.startswith(f"video{k}"):
            return f"Video {k}"
    return name


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    flt = json.dumps([{"field": "campaign.id", "operator": "IN", "value": list(CAMPS)}])
    life = g._get_all(f"{ACCT}/insights", {
        "level": "ad", "limit": 200, "date_preset": "maximum", "filtering": flt,
        "fields": "ad_id,ad_name,adset_name,campaign_id,campaign_name,spend,impressions,cpm,inline_link_clicks,"
                  "inline_link_click_ctr,cost_per_inline_link_click,actions,date_start,date_stop"})
    rows, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, "Register"), 0.0)
    reg = Counter((cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad)) for x in rows)
    regp = Counter()
    for (c, a_s, a), n in reg.items():
        regp[(c, a)] += n

    def reg_for(r):
        k = (cpa.ad_key(r.get("campaign_name") or ""), cpa.ad_key(r.get("adset_name") or ""), cpa.ad_key(r.get("ad_name") or ""))
        if reg.get(k):
            return reg[k]
        # sheet campaign may be cut short: prefix match on campaign, exact ad set + ad
        return sum(n for (c, a_s, a), n in reg.items() if a_s == k[1] and a == k[2] and c and k[0].startswith(c))

    camp_t = defaultdict(lambda: Counter())
    vid_t = defaultdict(lambda: Counter())
    log.info("每支广告，从开始跑到现在（SG老户）：")
    for r in sorted(life, key=lambda r: (CAMPS.get(r["campaign_id"], ""), vid(r.get("ad_name", "")))):
        sp, im, lc = _f(r.get("spend")), _f(r.get("impressions")), _f(r.get("inline_link_clicks"))
        lpv, mr, rr = act(r.get("actions"), "landing_page_view"), extract_results(r.get("actions"), tok), reg_for(r)
        st = g.get_object(r["ad_id"], "effective_status").get("effective_status")
        cn, v = CAMPS.get(r["campaign_id"], r["campaign_id"]), vid(r.get("ad_name", ""))
        for t in (camp_t[cn], vid_t[v]):
            t["sp"] += sp; t["im"] += im; t["lc"] += lc; t["lpv"] += lpv; t["mr"] += mr; t["rr"] += rr
        log.info("  %-24s · %s · ad %s · %s · %s~%s · 花 RM%.2f · 曝光 %.0f · CPM RM%.2f · 点击 %.0f · CTR %.2f%% · CPC RM%.2f · "
                 "落地页 %.0f · Meta 报名 %.0f · 报名表 %d · CPL %s · 落地页→报名 %s", cn, v, r["ad_id"], st,
                 r.get("date_start"), r.get("date_stop"), sp, im, _f(r.get("cpm")), lc, _f(r.get("inline_link_click_ctr")),
                 _f(r.get("cost_per_inline_link_click")), lpv, mr, rr,
                 f"RM{sp / max(mr, rr):.2f}" if max(mr, rr) else "—", f"{max(mr, rr) / lpv * 100:.1f}%" if lpv else "—")

    def line(lbl, t):
        best = max(t["mr"], t["rr"])
        return (f"{lbl} · 花 RM{t['sp']:.2f} · 曝光 {t['im']:.0f} · CPM RM{t['sp'] / t['im'] * 1000:.2f} · 点击 {t['lc']:.0f} · "
                f"CTR {t['lc'] / t['im'] * 100:.2f}% · CPC RM{t['sp'] / t['lc']:.2f} · 落地页 {t['lpv']:.0f} · Meta 报名 {t['mr']:.0f} · "
                f"报名表 {t['rr']:.0f} · CPL {('RM%.2f' % (t['sp'] / best)) if best else '—'} · 落地页→报名 "
                f"{('%.1f%%' % (best / t['lpv'] * 100)) if t['lpv'] else '—'}") if t["im"] and t["lc"] else f"{lbl} · 没数据"

    log.info("═" * 100)
    log.info("按 campaign（受众）合计：")
    for cn, t in camp_t.items():
        log.info("  %s", line(cn, t))
    log.info("按片合计（三个受众加起来）：")
    for v, t in sorted(vid_t.items()):
        log.info("  %s", line(v, t))
    log.info("═" * 100)
    log.info("每天（campaign）：")
    for cid, cn in CAMPS.items():
        days = g._get_all(f"{cid}/insights", {"date_preset": "maximum", "time_increment": 1, "fields": "spend,actions,date_start"})
        log.info("  %s：%s", cn, " · ".join(f"{d['date_start'][5:]} RM{_f(d.get('spend')):.2f}/{extract_results(d.get('actions'), tok):.0f}"
                                           for d in days))
    tot = Counter()
    for t in camp_t.values():
        tot.update(t)
    final_summary(log, line("21 支合计", tot))


if __name__ == "__main__":
    main()
