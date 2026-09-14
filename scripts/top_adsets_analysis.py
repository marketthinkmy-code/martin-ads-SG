"""Top-converting AD SETS from the Paid Student List. Read-only.

Operator (14 Sep): the new 15-ad build's ad sets should be the account's proven
converters — "成交转化最多的 ad set，3 个，给我看看，确保数据分析都对".

So: group provably-SG sales by UTM Ads Set (the sheet's own column), rank by lifetime
count with 60d/30d recency, fold each ad-set NAME's lifetime spend from Meta insights
(one name can run as several copies) for a name-level CPA, and for the top names read the
CURRENT Meta ad set carrying that name and print its actual targeting digest — so the
operator can verify both the numbers and what audience the name really is.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def targeting_digest(t: Dict[str, Any]) -> str:
    bits: List[str] = []
    geo = ((t.get("geo_locations") or {}).get("countries")) or []
    bits.append("/".join(geo) or "?")
    bits.append(f"{t.get('age_min', '?')}-{t.get('age_max', '?')}")
    adv = (t.get("targeting_automation") or {}).get("advantage_audience")
    bits.append(f"Adv+{'ON' if adv else 'OFF'}")
    names: List[str] = []
    for spec in (t.get("flexible_spec") or [{}]):
        for kind in ("interests", "behaviors", "life_events", "family_statuses"):
            for it in spec.get(kind) or []:
                names.append(it.get("name") or it.get("id") or "?")
    for kind in ("interests", "behaviors"):
        for it in t.get(kind) or []:
            names.append(it.get("name") or it.get("id") or "?")
    for ca in t.get("custom_audiences") or []:
        names.append(f"CA:{ca.get('name') or ca.get('id')}")
    bits.append(" + ".join(names[:6]) if names else "Broad（无 interest/behavior）")
    return " · ".join(bits)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60, d30 = today - dt.timedelta(days=60), today - dt.timedelta(days=30)

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    life: Counter = Counter()
    w60: Counter = Counter()
    w30: Counter = Counter()
    disp: Dict[str, str] = {}
    n_sg = 0
    for x in sales:
        if not _sg(x.campaign):
            continue
        n_sg += 1
        k = x.adset.strip() or "∅ (无 UTM adset)"
        disp.setdefault(k, k)
        life[k] += 1
        if x.date and x.date >= d60:
            w60[k] += 1
        if x.date and x.date >= d30:
            w30[k] += 1
    log.info("Paid Student List: %d provably-SG sales · %d distinct UTM Ads Set values",
             n_sg, len(life))

    # lifetime spend per ad-set NAME (folded across copies)
    name_spend: Dict[str, float] = defaultdict(float)
    for r in g.account_insights(acct, level="adset", fields="adset_id,adset_name,spend",
                                date_preset="maximum"):
        try:
            name_spend[cpa.norm(r.get("adset_name") or "")] += float(r.get("spend") or 0)
        except (TypeError, ValueError):
            continue

    log.info("═" * 110)
    log.info("按 UTM Ads Set 的 SG 成交排行（life · 60d · 30d · 名字口径花费 · CPA）")
    log.info("═" * 110)
    ranked = sorted(life.items(), key=lambda kv: (kv[1], w60[kv[0]], w30[kv[0]]), reverse=True)
    for k, n in ranked[:12]:
        sp = name_spend.get(k, 0.0)
        cpa_v = sp / n if n else 0.0
        log.info("  %2d 单 (60d %d · 30d %d) · 花 RM%-9s · CPA RM%-8s %s",
                 n, w60[k], w30[k], f"{sp:,.0f}", f"{cpa_v:,.0f}", disp[k][:60])

    # what the top names actually target, per the CURRENT Meta ad sets
    adsets = g._get_all(f"{acct}/adsets", {"fields": "id,name,campaign_id", "limit": 500})
    camps = {c["id"]: c.get("name") for c in g._get_all(
        f"{acct}/campaigns", {"fields": "id,name", "limit": 200})}
    log.info("═" * 110)
    log.info("Top 名字的实际 targeting（取该名字最新的一个 ad set 读定向）:")
    for k, n in ranked[:6]:
        matches = [a for a in adsets if cpa.norm(a.get("name") or "") == k]
        if not matches:
            matches = [a for a in adsets if k and k in cpa.norm(a.get("name") or "")]
        if not matches:
            log.info("▸ %-46s ∅ 账户里找不到同名 ad set", disp[k][:46])
            continue
        best = max(matches, key=lambda a: int(a["id"]))
        try:
            t = g.get_object(best["id"], "targeting").get("targeting") or {}
            log.info("▸ %-46s (%d 个同名 copy)", disp[k][:46], len(matches))
            log.info("    %s", targeting_digest(t))
            log.info("    例: %s › adset %s", (camps.get(best.get('campaign_id')) or '?')[:48],
                     best["id"])
        except Exception as exc:  # noqa: BLE001
            log.info("▸ %-46s targeting 读取失败: %s", disp[k][:46], exc)

    final_summary(log, f"Ranked {len(life)} UTM ad-set names over {n_sg} provably-SG sales; "
                       f"top rows + real targeting digests above. Read-only.")


if __name__ == "__main__":
    main()
