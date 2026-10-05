"""Ad-set ROI ranking across BOTH accounts (read-only, 5 Oct).

Operator is opening the three Qing 15岁+ videos on the HK account as a new ABO
campaign and wants 高回报 ad-set recommendations. The old adset_roas report only
sees the old SG account; this folds old SG + HK by ad-set NAME key and joins the
Paid Student List by UTM Ads Set, in two windows:
    90d   — spend / leads / CPL / sales / CPA / ROAS
    era   — since 2026-09-25 (HK account era), same columns
plus lifetime sheet sales per ad-set name. For every ranked ad set, one live
representative ad set id is resolved and its targeting signature printed
(age · gender · Adv+ · interests / LAL / custom audiences · placements) so a
recommendation can be cloned faithfully. No writes.
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

HK_ACCT = "act_1179668409969241"
ERA = dt.date(2026, 9, 25)
PRICE = 2399.0


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def signature(t: Dict[str, Any]) -> str:
    bits = []
    bits.append(f"{t.get('age_min')}-{t.get('age_max')}")
    g = t.get("genders")
    bits.append({1: "男", 2: "女"}.get((g or [0])[0], "全") if g else "全")
    adv = (t.get("targeting_automation") or {}).get("advantage_audience")
    bits.append(f"Adv+{'ON' if adv else 'OFF'}" if adv is not None else "Adv+?")
    ints = []
    for fs in t.get("flexible_spec") or []:
        for kind in ("interests", "behaviors", "life_events", "family_statuses",
                     "education_statuses", "work_positions"):
            ints += [x.get("name") for x in fs.get(kind) or [] if x.get("name")]
    if ints:
        bits.append("兴趣:" + "/".join(ints[:6]) + ("…" if len(ints) > 6 else ""))
    ca = [x.get("name") for x in t.get("custom_audiences") or [] if x.get("name")]
    if ca:
        bits.append("受众:" + "/".join(ca[:3]) + ("…" if len(ca) > 3 else ""))
    ex = t.get("excluded_custom_audiences") or []
    if ex:
        bits.append(f"排除{len(ex)}")
    if t.get("publisher_platforms"):
        bits.append("手动版位")
    return " · ".join(bits)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d90 = today - dt.timedelta(days=90)
    accounts = [("SG老", s.meta.account_path), ("HK", HK_ACCT)]

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id,
                                                             s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n90: Dict[str, int] = defaultdict(int)
    nera: Dict[str, int] = defaultdict(int)
    nall: Dict[str, int] = defaultdict(int)
    for x in sales:
        if not x.date or not _sg(x.campaign):
            continue
        k = cpa.ad_key(x.adset or "")
        if not k:
            continue
        nall[k] += 1
        if x.date >= d90:
            n90[k] += 1
        if x.date >= ERA:
            nera[k] += 1

    rows: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "sp90": 0.0, "ld90": 0.0, "spe": 0.0, "lde": 0.0, "names": set(), "accts": set()})
    for label, acct in accounts:
        for since, spk, ldk in ((d90, "sp90", "ld90"), (ERA, "spe", "lde")):
            for r in g._get_all(f"{acct}/insights",
                                {"level": "adset", "limit": 500,
                                 "fields": "adset_id,adset_name,spend,actions",
                                 "time_range": json.dumps({"since": since.isoformat(),
                                                           "until": today.isoformat()})}):
                k = cpa.ad_key(r.get("adset_name") or "")
                if not k:
                    continue
                d = rows[k]
                try:
                    d[spk] += float(r.get("spend") or 0)
                except (TypeError, ValueError):
                    pass
                d[ldk] += extract_results(r.get("actions"), token)
                d["names"].add((r.get("adset_name") or "").strip())
                d["accts"].add(label)

    # representative live ad set per key (newest), for the targeting signature
    rep: Dict[str, Dict[str, Any]] = {}
    for label, acct in accounts:
        for a in g._get_all(f"{acct}/adsets",
                            {"fields": "id,name,created_time,targeting,effective_status",
                             "limit": 500}):
            k = cpa.ad_key(a.get("name") or "")
            if k in rows and (k not in rep or a.get("created_time", "") > rep[k].get("created_time", "")):
                a["_acct"] = label
                rep[k] = a

    def fmt(k: str) -> str:
        d = rows[k]
        cpl90 = f"CPL{d['sp90'] / d['ld90']:.0f}" if d["ld90"] else "零L"
        cpa90 = f"CPA{d['sp90'] / n90[k]:,.0f}" if n90[k] else "无单"
        roas90 = (n90[k] * PRICE / d["sp90"]) if d["sp90"] else 0.0
        cple = f"CPL{d['spe'] / d['lde']:.0f}" if d["lde"] else "零L"
        cpae = f"CPA{d['spe'] / nera[k]:,.0f}" if nera[k] else "无单"
        return (f"90d 花{d['sp90']:>6.0f} {int(d['ld90']):>3}L {cpl90:<7} {n90[k]:>2}单 {cpa90:<9} ROAS{roas90:4.2f} │ "
                f"era 花{d['spe']:>5.0f} {int(d['lde']):>3}L {cple:<7} {nera[k]:>2}单 {cpae:<9} │ 全史{nall[k]:>3}单")

    cands = [k for k in rows if rows[k]["sp90"] >= 150]
    log.info("窗口：90d=%s起 · era=%s起 · 候选=90d花费≥RM150 的 ad set（两账户按名字折叠）共 %d 个",
             d90, ERA, len(cands))

    log.info("═" * 150)
    log.info("A) 按 90d 成交数排序（真正的回报）")
    for k in sorted(cands, key=lambda x: (-n90[x], rows[x]["sp90"] / max(n90[x], 1)))[:14]:
        nm = sorted(rows[k]["names"], key=len)[0]
        log.info("▸ %-40s [%s] %s", nm[:40], "+".join(sorted(rows[k]["accts"])), fmt(k))
        r = rep.get(k)
        if r:
            log.info("      %s · %s · %s", r["id"], r.get("effective_status"), signature(r.get("targeting") or {}))

    log.info("═" * 150)
    log.info("B) 按 era（9/25 起）CPL 排序，花费≥RM100（最近的 lead 效率）")
    era_c = [k for k in rows if rows[k]["spe"] >= 100 and rows[k]["lde"] > 0]
    for k in sorted(era_c, key=lambda x: rows[x]["spe"] / rows[x]["lde"])[:12]:
        nm = sorted(rows[k]["names"], key=len)[0]
        log.info("▸ %-40s [%s] %s", nm[:40], "+".join(sorted(rows[k]["accts"])), fmt(k))
        r = rep.get(k)
        if r:
            log.info("      %s · %s · %s", r["id"], r.get("effective_status"), signature(r.get("targeting") or {}))

    log.info("═" * 150)
    log.info("C) 全史成交最多的 ad set 名（不限窗口，看哪些受众长期出单）")
    for k in sorted(nall, key=lambda x: -nall[x])[:12]:
        nm = sorted(rows[k]["names"], key=len)[0] if k in rows and rows[k]["names"] else k
        log.info("▸ %-40s 全史 %3d 单 · %s", nm[:40], nall[k],
                 fmt(k) if k in rows else "（90d 内两账户无花费）")
    final_summary(log, "ad-set ranking done — recommendation goes to chat.")


if __name__ == "__main__":
    main()
