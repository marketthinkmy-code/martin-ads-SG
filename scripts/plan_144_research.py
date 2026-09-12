"""Research for the operator's new SG 1-4-4: targeting keywords + top-converting ads.

Read-only. Two jobs in one run:

1. TARGETING — resolve the operator's four ad-set themes into real Meta targeting options
   (interest/behavior ids with global audience sizes), via /search type=adinterest and the
   behaviors category list:
     · Engaged Shoppers (behavior) · Vitamins · General health & wellness · Supplements

2. ADS — the operator pointed at a tab (gid 1500782859) of the Paid Student List workbook:
   count conversions per UTM ad name (provably-SG split, lifetime/60d/30d), rank, and for
   the top names resolve the highest-spend existing ad -> its page post id
   (effective_object_story_id) so the build can reuse the post with its social proof.

PII discipline: no names/phones/emails in logs — dates, UTM values and counts only.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.drive import build_credentials
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

TARGET_GID = 1500782859

INTEREST_QUERIES = {
    "Vitamins": ["vitamins", "multivitamin", "vitamin D"],
    "General health & wellness": ["health and wellness", "wellness", "health"],
    "Supplements": ["dietary supplement", "nutritional supplement", "supplements"],
}


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60, d30 = today - dt.timedelta(days=60), today - dt.timedelta(days=30)

    # ── 1) the tab the operator pointed at ─────────────────────────────────────
    from googleapiclient.discovery import build
    svc = build("sheets", "v4", credentials=build_credentials(s.secrets.google_sa_json),
                cache_discovery=False)
    meta = svc.spreadsheets().get(spreadsheetId=s.cpa.spreadsheet_id,
                                  fields="sheets.properties").execute()
    title = None
    for sh in meta.get("sheets", []):
        p = sh["properties"]
        if p.get("sheetId") == TARGET_GID:
            title = p.get("title")
    if not title:
        raise SystemExit(f"!! no tab with gid {TARGET_GID} in the workbook")
    rows = (svc.spreadsheets().values()
            .get(spreadsheetId=s.cpa.spreadsheet_id, range=title,
                 valueRenderOption="FORMATTED_VALUE", dateTimeRenderOption="FORMATTED_STRING")
            .execute().get("values", []))
    log.info("── tab %r: %d data rows", title, max(0, len(rows) - 1))
    if not rows:
        raise SystemExit("!! tab empty")
    header = rows[0]

    def col(*names):
        for i, h in enumerate(header):
            k = re.sub(r"\W+", "", (h or "").lower())
            for n in names:
                if re.sub(r"\W+", "", n.lower()) in k:
                    return i
        return None

    c_date = col("created date", "date", "created")
    c_camp = col("utm campaign")
    c_ad = col("utm ads name", "utm ad name", "utm ad")
    log.info("── header: %s · cols date=%s campaign=%s ad=%s", header, c_date, c_camp, c_ad)

    disp: Dict[str, str] = {}
    life_all: Counter = Counter()
    life_sg: Counter = Counter()
    sg60: Counter = Counter()
    sg30: Counter = Counter()
    for r in rows[1:]:
        def get(i):
            return (r[i] if i is not None and i < len(r) else "") or ""
        ad = get(c_ad).strip()
        k = cpa.ad_key(ad)
        if not k:
            continue
        disp.setdefault(k, ad)
        life_all[k] += 1
        if _sg(get(c_camp)):
            life_sg[k] += 1
            d = cpa.parse_date(get(c_date))
            if d and d >= d60:
                sg60[k] += 1
            if d and d >= d30:
                sg30[k] += 1

    # name-key lifetime spend -> CPA + representative (highest-spend) ad per key
    key_spend: Dict[str, float] = defaultdict(float)
    best_ad: Dict[str, tuple] = {}
    for row in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                  date_preset="maximum"):
        k = cpa.ad_key(row.get("ad_name") or "")
        try:
            sp = float(row.get("spend") or 0)
        except (TypeError, ValueError):
            sp = 0.0
        key_spend[k] += sp
        if k and (k not in best_ad or sp > best_ad[k][1]):
            best_ad[k] = (row.get("ad_id"), sp, row.get("ad_name"))

    log.info("═" * 100)
    log.info("轉化排行（tab %r · 按 SG 成交数）· life/60d/30d · 名字口径 CPA · 代表 ad", title)
    log.info("═" * 100)
    ranked = sorted(life_sg.items(), key=lambda kv: (kv[1], sg60[kv[0]]), reverse=True)[:10]
    tops: List[str] = []
    for k, n in ranked:
        cpa_v = key_spend.get(k, 0.0) / n if n else 0.0
        rep = best_ad.get(k)
        rep_txt = f"ad {rep[0]} (spend RM{rep[1]:,.0f})" if rep else "∅ 账户里找不到同名 ad"
        log.info("  %2d SG (60d %d · 30d %d) · CPA RM%s · %s", n, sg60[k], sg30[k],
                 f"{cpa_v:,.0f}", disp[k][:58])
        log.info("       全表 %d 行 · %s", life_all[k], rep_txt)
        tops.append(k)

    # page post ids for the top 6 (build reuses existing posts)
    log.info("═" * 100)
    log.info("Top 候选的 existing post id（effective_object_story_id）:")
    for k in tops[:6]:
        rep = best_ad.get(k)
        if not rep:
            continue
        try:
            info = g.get_object(rep[0], "name,effective_status,creative{effective_object_story_id}")
            post = ((info.get("creative") or {}).get("effective_object_story_id")) or "?"
            log.info("   %-55s post %s · rep-ad %s (%s)", disp[k][:55], post, rep[0],
                     info.get("effective_status"))
        except Exception as exc:  # noqa: BLE001
            log.info("   %-55s post 解析失败: %s", disp[k][:55], exc)

    # ── 2) targeting keywords ──────────────────────────────────────────────────
    log.info("═" * 100)
    log.info("TARGETING 关键词（全球受众规模，单位 M=百万）")
    log.info("═" * 100)
    log.info("▸ Engaged Shoppers（behavior 类）:")
    try:
        beh = g._request("GET", "search",
                         params={"type": "adTargetingCategory", "class": "behaviors",
                                 "limit": 500}).get("data", [])
        hits = [b for b in beh if "shopper" in (b.get("name") or "").lower()]
        for b in hits or beh[:0]:
            lo = (b.get("audience_size_lower_bound") or 0) / 1e6
            hi = (b.get("audience_size_upper_bound") or 0) / 1e6
            log.info("   id %-16s %-34s %s  %.0fM–%.0fM", b.get("id"), b.get("name"),
                     "/".join(b.get("path") or []), lo, hi)
        if not hits:
            log.info("   (behaviors 列表里没有含 shopper 的条目)")
    except Exception as exc:  # noqa: BLE001
        log.info("   behaviors 查询失败: %s", exc)

    for group, queries in INTEREST_QUERIES.items():
        log.info("▸ %s（interest）:", group)
        seen = set()
        for q in queries:
            try:
                data = g._request("GET", "search",
                                  params={"type": "adinterest", "q": q, "limit": 8,
                                          "locale": "en_US"}).get("data", [])
            except Exception as exc:  # noqa: BLE001
                log.info("   q=%r 查询失败: %s", q, exc)
                continue
            for it in data:
                if it.get("id") in seen:
                    continue
                seen.add(it.get("id"))
                lo = (it.get("audience_size_lower_bound") or 0) / 1e6
                hi = (it.get("audience_size_upper_bound") or 0) / 1e6
                path = "/".join(it.get("path") or [])
                log.info("   id %-16s %-34s %-40s %.0fM–%.0fM",
                         it.get("id"), (it.get("name") or "")[:34], path[:40], lo, hi)

    final_summary(log, f"Tab {title!r}: ranked SG conversions per ad name (top {len(ranked)} "
                       f"shown) + existing post ids; targeting options listed for the 4 "
                       f"ad-set themes. Read-only.")


if __name__ == "__main__":
    main()
