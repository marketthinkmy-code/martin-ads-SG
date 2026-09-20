"""Enforce the operator's 30-day-CPA board discipline (20 Sep). MUTATING, operator-ordered.

Operator: "我不希望我现在开着的广告，都是很久没有成交过的 / cpa 不合格的（新广告例外）。
确保我现在的 sg 开着的广告，cpa 30day 的都有达标，才开着。我要确保留下的每一分钱都在
「达标 / 新 / 素材有近单」."

Rule, per LIVE ad name (copies folded, provably-SG sales only):
    KEEP 达标   ≥1 SG sale in the last 30 days AND 30d CPA (30d spend ÷ 30d sales)
                ≤ RM960 (config max_acceptable) — "素材有近单" is this same bucket:
                a recent sale on any copy of the creative qualifies the name.
    KEEP 新     every live copy created within the last 14 days AND the name's lifetime
                spend is under the RM1,000 fair-judgment floor (config min_spend_myr) —
                the daily zero-reg kill keeps governing these.
    CLOSE       everything else: no 30d sale, or 30d CPA over RM960.

Close = pause the ad + its ad set once emptied; campaigns untouched. Idempotent; audit in
state/enforce_cpa30_0920_log.json.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

LOG_PATH = Path("state") / "enforce_cpa30_0920_log.json"
NEW_AD_MAX_AGE_DAYS = 14


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = today - dt.timedelta(days=30)
    new_line = today - dt.timedelta(days=NEW_AD_MAX_AGE_DAYS)
    acc = s.cpa.max_acceptable_myr
    judge_floor = s.cpa.min_spend_myr

    from adbot.clients.sheets import SheetsClient
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    s30: Dict[str, int] = {}
    last_sale: Dict[str, dt.date] = {}
    for x in sales:
        if not _sg(x.campaign):
            continue
        k = cpa.ad_key(x.ad)
        if x.date:
            if x.date >= d30:
                s30[k] = s30.get(k, 0) + 1
            if k not in last_sale or x.date > last_sale[k]:
                last_sale[k] = x.date

    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,status,effective_status,adset_id,created_time",
                      "limit": 500})
    live_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for a in ads:
        if a.get("effective_status") != "ACTIVE":
            continue
        k = cpa.ad_key(a.get("name") or "")
        if k:
            live_by_key.setdefault(k, []).append(a)

    def fold_spend(**kw) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend", **kw):
            k = cpa.ad_key(r.get("ad_name") or "")
            try:
                out[k] = out.get(k, 0.0) + float(r.get("spend") or 0)
            except (TypeError, ValueError):
                continue
        return out

    spend30 = fold_spend(time_range={"since": d30.isoformat(), "until": today.isoformat()})
    spend_life = fold_spend(date_preset="maximum")

    audit: List[Dict[str, Any]] = []
    kept: List[str] = []
    closed: List[str] = []
    log.info("═" * 108)
    log.info("30d-CPA 板面纪律 · 窗口 %s → %s · 达标线 RM%.0f · 新=全部 copy <%dd 且名字花费 <RM%.0f",
             d30, today, acc, NEW_AD_MAX_AGE_DAYS, judge_floor)
    log.info("═" * 108)
    for k, copies in sorted(live_by_key.items(), key=lambda kv: kv[0]):
        name = (copies[0].get("name") or "").strip()
        n30, sp30 = s30.get(k, 0), spend30.get(k, 0.0)
        lifesp = spend_life.get(k, 0.0)
        cpa30 = sp30 / n30 if n30 else 0.0
        ages_ok = all((a.get("created_time") or "9999")[:10] >= new_line.isoformat()
                      for a in copies)
        is_new = ages_ok and lifesp < judge_floor
        ls = last_sale.get(k)
        stats = (f"30d: 花 RM{sp30:,.0f} · {n30}单 · CPA {'RM' + format(cpa30, ',.0f') if n30 else '—'}"
                 f" · 终身花 RM{lifesp:,.0f}{' · 最后成交 ' + ls.isoformat() if ls else ' · 从未成交'}")
        if n30 >= 1 and cpa30 <= acc:
            log.info("▸ KEEP 达标   %-36s %s", name[:36], stats)
            kept.append(f"{name[:22]}(达标)")
            continue
        if is_new:
            log.info("▸ KEEP 新     %-36s %s", name[:36], stats)
            kept.append(f"{name[:22]}(新)")
            continue
        reason = (f"30d CPA RM{cpa30:,.0f} 超 RM{acc:.0f}" if n30
                  else "30d 无 SG 成交且不是新素材")
        log.info("▸ CLOSE       %-36s %s → %s", name[:36], stats, reason)
        for a in copies:
            g.update_status(a["id"], "PAUSED")
            a["status"] = "PAUSED"
            audit.append({"act": "pause_ad", "id": a["id"], "name": name, "reason": reason})
            sid = a.get("adset_id")
            others = [x for x in ads if x.get("adset_id") == sid and x["id"] != a["id"]
                      and x.get("status") == "ACTIVE"]
            if sid and not others:
                g.update_status(sid, "PAUSED")
                audit.append({"act": "pause_adset", "id": sid})
                log.info("    └ PAUSED ad %s + adset %s", a["id"], sid)
            else:
                log.info("    └ PAUSED ad %s", a["id"])
            time.sleep(1.0)
        closed.append(f"{name[:22]}({reason})")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(
        {"run": dt.datetime.utcnow().isoformat() + "Z", "rule": "cpa30<=%s or new" % acc,
         "mutations": audit}, ensure_ascii=False, indent=2) + "\n")
    log.info("═" * 108)
    final_summary(log, f"30d-CPA discipline enforced: kept {len(kept)} names "
                       f"[{'; '.join(kept)}]; closed {len(closed)} "
                       f"[{'; '.join(closed) or '—'}]. {len(audit)} mutations; audit saved.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
