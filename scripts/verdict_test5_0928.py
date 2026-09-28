"""新片 5 支测试 · 7 天判决 (read-only, 28 Sep).

Operator's spec on 9/21: 1-1-5 · RM100/day · F&R · 「7 天不动」 — the 7 days are up.
The test ran twice: the ORIGINAL on the old account (state/entities_test155_fr_0921.json,
9/21 → operator closed the old account ~9/25-26) and the CARBON COPY on the new account
(ported 9/25 inside state/entities_newacct_0925.json's "test" unit, still live).
Names are identical by design, so per-ad totals fold across both accounts.

For each of the 5 ads: spend / link clicks / CPC / leads / CPL per account and combined
(9/21 → today), plus SG sales since 9/21 from the Paid Student List (folded-name match)
and each ad's CPA where it sold. Verdicts follow the operator's discipline: sale with
CPA ≤ RM960 keeps; no sale is judged by CPL vs the RM95 target within the new-ad window
(14d / RM1,000 lifetime). Prints both campaigns' switch state, and flags sheet lag if the
latest SG sale predates the weekend. READ-ONLY — the verdict table goes to the operator
and nothing changes until they approve.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
START = dt.date(2026, 9, 21)
ORDER = ["hook1", "nh4", "xh7", "xh3", "xh6"]


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    old_acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    tr = json.dumps({"since": START.isoformat(), "until": today.isoformat()})
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    t155 = json.loads(Path("state/entities_test155_fr_0921.json").read_text())
    newst = json.loads(Path("state/entities_newacct_0925.json").read_text())
    new_unit = (newst.get("units") or {}).get("test") or {}
    new_by_name = {cpa.ad_key(n): i for n, i in (new_unit.get("ads") or {}).items()}

    # exact names + statuses from the old originals
    meta_by_key: Dict[str, Dict[str, Any]] = {}
    for k in ORDER:
        ad = g.get_object(t155["ads"][k], "name,effective_status")
        nk = cpa.ad_key(ad.get("name") or "")
        meta_by_key[k] = {"name": (ad.get("name") or "").strip(), "key": nk,
                          "old_id": t155["ads"][k], "old_eff": ad.get("effective_status"),
                          "new_id": new_by_name.get(nk)}

    def pull(acct: str) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500, "time_range": tr,
                             "fields": "ad_id,spend,actions,inline_link_clicks"}):
            d = out[r.get("ad_id")]
            try:
                d["sp"] += float(r.get("spend") or 0)
                d["lc"] += float(r.get("inline_link_clicks") or 0)
            except (TypeError, ValueError):
                pass
            d["ld"] += extract_results(r.get("actions"), token)
        return out

    old_perf, new_perf = pull(old_acct), pull(NEW_ACCT)

    # sheet: SG sales since START, folded-name match
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id,
                                                             s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n_sales: Dict[str, int] = defaultdict(int)
    sale_dates: Dict[str, list] = defaultdict(list)
    latest: dt.date | None = None
    keys = {m["key"] for m in meta_by_key.values()}
    for x in sales:
        if not _sg(x.campaign) or not x.date:
            continue
        if latest is None or x.date > latest:
            latest = x.date
        if x.date >= START:
            k = cpa.ad_key(x.ad)
            if k in keys:
                n_sales[k] += 1
                sale_dates[k].append(x.date.isoformat())

    log.info("名单最新 SG 成交日: %s%s", latest,
             "  ⚠️ 早于周末 — 名单可能还没更新，判决先按现有数据" if latest and latest < dt.date(2026, 9, 26) else "")
    log.info("═" * 110)
    log.info("新片 5 支 · 7 天判决（%s → %s · 两账户同名合并 · 达标线 CPL RM95 / CPA RM%.0f）",
             START, today, acc)

    rows = []
    for k in ORDER:
        m = meta_by_key[k]
        o = old_perf.get(m["old_id"], {})
        n = new_perf.get(m["new_id"], {}) if m["new_id"] else {}
        sp = float(o.get("sp", 0)) + float(n.get("sp", 0))
        lc = float(o.get("lc", 0)) + float(n.get("lc", 0))
        ld = float(o.get("ld", 0)) + float(n.get("ld", 0))
        ns = n_sales.get(m["key"], 0)
        cpl = sp / ld if ld else 0.0
        cpa_v = sp / ns if ns else 0.0
        if ns and cpa_v <= acc:
            v = f"✅ 有单达标（CPA RM{cpa_v:,.0f}）— 留，候选加预算"
        elif ns and cpa_v <= hard:
            v = f"🤔 有单但 CPA RM{cpa_v:,.0f} 在 960-1200 边缘 — 留守观察"
        elif ns:
            v = f"❌ 有单但 CPA RM{cpa_v:,.0f} 超硬线 — 建议关"
        elif ld and cpl <= 95:
            v = f"▶️ 无单 · CPL RM{cpl:,.0f} 达标 — 新广告窗口内继续跑"
        elif ld and cpl <= 142.5:
            v = f"⚠️ 无单 · CPL RM{cpl:,.0f} 超标 — 建议减一档或让位"
        elif ld:
            v = f"❌ 无单 · CPL RM{cpl:,.0f} 爆表 — 建议关"
        else:
            v = ("❌ 零注册且花费已过杀线 — 建议关" if sp >= 142.5
                 else "⏸ 零注册但花费还小 — 可再给一点空间")
        log.info("▸ %s", m["name"])
        log.info("    老账户 花 RM%-8.2f %dL · 新账户 花 RM%-8.2f %dL · 合计 花 RM%-8.2f 点击 %d "
                 "CPC %s · %dL CPL %s",
                 o.get("sp", 0.0), int(o.get("ld", 0)), n.get("sp", 0.0), int(n.get("ld", 0)),
                 sp, int(lc), f"RM{sp / lc:.2f}" if lc else "—", int(ld),
                 f"RM{cpl:,.0f}" if ld else "—")
        log.info("    本场成交 %d 单%s → %s", ns,
                 f"（{', '.join(sale_dates[m['key']])}）" if ns else "", v)
        rows.append(f"{k}:{int(ld)}L/{ns}单")

    for label, cid in (("老账户测试 campaign", t155.get("campaign_id")),
                       ("新账户拷贝 campaign", (newst.get("campaigns") or {}).get("test"))):
        if not cid:
            continue
        info = g.get_object(cid, "name,effective_status,daily_budget")
        asets = g._get_all(f"{cid}/adsets", {"fields": "daily_budget", "limit": 10})
        b = int(info.get("daily_budget") or 0) or sum(int(a.get("daily_budget") or 0)
                                                      for a in asets)
        log.info("%s %s: %s · RM%d/day", label, cid, info.get("effective_status"), b // 100)

    final_summary(log, f"7-day verdict data ready ({'; '.join(rows)}); latest sheet sale "
                       f"{latest}. Read-only — verdict table goes to the operator, nothing "
                       f"changed.")


if __name__ == "__main__":
    main()
