"""Under-tested creatives (read-only, 19 Oct): stopped before they ever got a fair spend.

Operator: 还有什么视频广告是老久了，or 没有被我花到钱就被我关掉的？ Per creative (ad name folded
by cpa.ad_key): lifetime spend + registrations on SG old + HK (the SG market), the same
creative's lifetime numbers on the MY account (read-only, a quality signal — rule 4), SG and
MY sales, whether anything is delivering now, first/last created date and the newest ad's
post id. Candidates: SG-market lifetime spend < RM90 (never reached the kill line), nothing
delivering, created in the last 365 days. Ranked by MY evidence (sales, then CPL).
No writes; MY is read only.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

SG_ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY_ACCT = "act_1011719073600566"
RUNNING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _mkt(c):
    c = cpa.norm(c)
    if "[sg]" in c or "martin-sg" in c or "martin sg" in c:
        return "SG"
    if "[my]" in c or "martin-my" in c or "martin my" in c:
        return "MY"
    return ""


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    cutoff = (today - dt.timedelta(days=365)).isoformat()

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), s.cpa.price_myr)
    nsale = defaultdict(lambda: {"SG": 0, "MY": 0})
    for x in sales:
        m = _mkt(x.campaign)
        if m:
            nsale[cpa.ad_key(x.ad)][m] += 1

    def life(acct):
        out = defaultdict(lambda: [0.0, 0.0])
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_name,spend,actions", "date_preset": "maximum"}):
            o = out[cpa.ad_key(r.get("ad_name") or "")]
            o[0] += _f(r.get("spend")); o[1] += extract_results(r.get("actions"), tok)
        return out

    sg = defaultdict(lambda: [0.0, 0.0])
    for _, acct in SG_ACCTS:
        for k, v in life(acct).items():
            sg[k][0] += v[0]; sg[k][1] += v[1]
    my = life(MY_ACCT)

    info = {}
    for label, acct in SG_ACCTS:
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,effective_status,created_time,creative{effective_object_story_id,object_type}", "limit": 500}):
            k = cpa.ad_key(a.get("name") or "")
            i = info.setdefault(k, {"name": a.get("name"), "first": "9999", "last": "", "live": False, "ad": None, "post": None, "acct": None, "type": None})
            ct = (a.get("created_time") or "")[:10]
            i["first"] = min(i["first"], ct)
            if a.get("effective_status") in RUNNING:
                i["live"] = True
            if ct >= i["last"]:
                cr = a.get("creative") or {}
                i.update(last=ct, ad=a["id"], post=cr.get("effective_object_story_id"), acct=label, name=a.get("name"),
                         type=cr.get("object_type"))

    rows = []
    for k, i in info.items():
        sp, ld = sg[k]
        if i["live"] or sp >= 90 or i["last"] < cutoff or not i["post"]:
            continue
        msp, mld = my.get(k, [0.0, 0.0])
        rows.append((nsale[k]["MY"], -(msp / mld) if mld else -9999, k))
    log.info("候选：SG 市场累计花费 < RM90、现在没在跑、一年内建过 · 共 %d 支 · 排序：MY 成交 → MY CPL", len(rows))
    log.info("═" * 120)
    for _, _, k in sorted(rows, reverse=True):
        i, (sp, ld), (msp, mld) = info[k], sg[k], my.get(k, [0.0, 0.0])
        log.info("▌%-44s 类型 %s · 建 %s 至 %s", (i["name"] or "")[:44], i["type"], i["first"], i["last"])
        log.info("    SG 市场：花 RM%.0f · %d lead · SG 成交 %d   |   MY：花 RM%.0f · %d lead · CPL %s · MY 成交 %d",
                 sp, int(ld), nsale[k]["SG"], msp, int(mld), f"{msp / mld:,.0f}" if mld else "—", nsale[k]["MY"])
        log.info("    最新广告 %s %s · post %s", i["acct"], i["ad"], i["post"])
    final_summary(log, f"under-tested · {len(rows)} candidates")


if __name__ == "__main__":
    main()
