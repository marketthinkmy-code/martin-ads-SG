"""Read-only: for the SG top-10 ad names, list every Meta ad variant.

Recomputes the SG top 10 (phone prefix +65) from the Paid Student List, then
pulls every Meta ad in the account whose normalised name matches one of those
10. For each variant prints: ad_id, effective_status, lifetime spend, region
tag (from the campaign-name prefix), campaign, ad set — sorted ACTIVE first
then by descending spend. Used to pick which specific ad IDs to un-pause.
"""
from __future__ import annotations

import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.settings import load_settings

PHONE_HEADERS = (
    "phone", "phonenumber", "phoneno", "mobile", "mobilenumber", "mobileno",
    "contact", "contactnumber", "contactno", "tel", "telephone",
    "whatsapp", "wa", "wsn", "whatsappnumber",
)


def _hkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def _find_phone_col(header) -> int:
    keys = [_hkey(h) for h in header]
    for needle in PHONE_HEADERS:
        for i, k in enumerate(keys):
            if k == needle:
                return i
    for needle in ("phone", "mobile", "whatsapp", "contact"):
        for i, k in enumerate(keys):
            if needle in k:
                return i
    return -1


def _is_sg(phone_raw: str) -> bool:
    phone = re.sub(r"[^\d+]", "", phone_raw or "").lstrip("+")
    return phone.startswith("65")


def _region_tag(campaign_name: str) -> str:
    """Best-effort region from the campaign-name prefix used by the operator."""
    s = campaign_name.strip()
    if s.startswith("[SG]") or s.startswith("MARTIN-SG") or "SG " in s[:8]:
        return "SG"
    if s.startswith("[BRUNEI]") or "BRUNEI" in s[:10].upper():
        return "BR"
    if s.startswith("[MY]") or s.startswith("MARTIN-MY"):
        return "MY"
    return "??"     # unprefixed = usually MY (the original account)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _status_rank(status: str) -> int:
    """ACTIVE first, then live-ish PAUSED tiers, then archived/deleted last."""
    order = [
        "ACTIVE",
        "PAUSED",
        "PENDING_REVIEW", "IN_PROCESS", "WITH_ISSUES",
        "ADSET_PAUSED",
        "CAMPAIGN_PAUSED",
        "DISAPPROVED",
        "ARCHIVED",
        "DELETED",
    ]
    return order.index(status) if status in order else len(order)


def main() -> None:
    s = load_settings()

    # ---- 1. Recompute SG top-10 from the Paid Student List --------------
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    header_idx, cols = 0, cpa.find_columns(values[0])
    for i, row in enumerate(values[:8]):
        cand = cpa.find_columns(row)
        if cand.get("campaign", -1) >= 0 and cand.get("ad", -1) >= 0:
            header_idx, cols = i, cand
            break
    header = values[header_idx]
    phone_col = _find_phone_col(header)
    sg_rows = [header]
    for row in values[header_idx + 1:]:
        phone_raw = row[phone_col] if 0 <= phone_col < len(row) else ""
        if _is_sg(phone_raw):
            sg_rows.append(row)
    sales, _c, _h = cpa.parse_sales(sg_rows, s.cpa.price_myr)
    name_sales = defaultdict(int)
    for sale in sales:
        if sale.ad:
            name_sales[sale.ad] += 1
    top10 = sorted(name_sales.items(), key=lambda kv: -kv[1])[:10]

    # ---- 2. Pull all Meta ads (any status) + lifetime spend -------------
    g = graph_client(s)
    acct = s.meta.account_path
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,effective_status,created_time,"
                  "campaign{name,effective_status},"
                  "adset{name,effective_status}",
        "limit": 500,
    })
    spend_by_ad_id = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", date_preset="maximum")}

    top10_keys = {name for name, _ in top10}
    by_name = defaultdict(list)
    for ad in ads:
        k = cpa.norm(ad.get("name", ""))
        if k in top10_keys:
            by_name[k].append(ad)

    print(f"SG top-10 ad-name variants  ·  scanned {len(ads)} Meta ads, "
          f"{sum(len(v) for v in by_name.values())} matched.\n")

    # ---- 3. Print each name and its variants ----------------------------
    for rank, (name_key, sg_cnt) in enumerate(top10, 1):
        variants = by_name.get(name_key, [])
        display = variants[0].get("name") if variants else name_key
        print("═" * 100)
        print(f"#{rank:>2}  {display}   ·   {sg_cnt} SG paid sales   ·   "
              f"{len(variants)} Meta variant(s)")

        if not variants:
            print("     (no Meta ad matches this name — normalisation mismatch?)\n")
            continue

        status_hist = defaultdict(int)
        region_hist = defaultdict(int)
        for v in variants:
            status_hist[v.get("effective_status", "?")] += 1
            region_hist[_region_tag((v.get("campaign") or {}).get("name", ""))] += 1
        print("     status counts:", ", ".join(
            f"{k}={n}" for k, n in sorted(status_hist.items(), key=lambda kv: _status_rank(kv[0]))))
        print("     region counts:", ", ".join(
            f"{k}={n}" for k, n in sorted(region_hist.items(), key=lambda kv: -kv[1])))
        print()

        variants.sort(key=lambda v: (
            _status_rank(v.get("effective_status", "?")),
            -spend_by_ad_id.get(v["id"], 0.0),
        ))
        print(f"     {'ad_id':>18}  {'status':>15}  {'spend':>8}  reg  "
              f"{'campaign':40}  ad set")
        print("     " + "-" * 110)
        for v in variants:
            camp = (v.get("campaign") or {}).get("name", "")
            adset = (v.get("adset") or {}).get("name", "")
            status = v.get("effective_status", "?")
            spend = spend_by_ad_id.get(v["id"], 0.0)
            reg = _region_tag(camp)
            print(f"     {v['id']:>18}  {status:>15}  RM {spend:>5,.0f}  "
                  f"{reg:>3}  {camp[:40]:40}  {adset[:32]}")
        print()


if __name__ == "__main__":
    main()
