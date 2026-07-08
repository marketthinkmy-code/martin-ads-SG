"""SG-only: paused Meta ads whose ad NAME has recent SG paid sales.

Answers: "Of ads paused (usually because of bad recent CPL/CPA), which ones are
still being credited with Singapore paid sales in the last 30 days — i.e.
worth re-activating and scaling?"

Filters:
  - SG: phone number in Paid Student List starts with 65 (+65)
  - RECENT: sale.date within the last 30 days (falls back to 90d / lifetime if
    30d is empty — the sheet has known date-parse issues on some rows)
  - PAUSED: Meta ad effective_status != ACTIVE
  - SCALE-WORTHY: lifetime ROAS on the Meta ad's own spend > 1 (revenue with
    zero variant spend counts as ∞, since the sale still landed for free)

Ranks candidates by (recent SG sales desc, ROAS desc). Only Meta ads in
campaigns whose region tag is SG are listed — BR/MY variants of the same
ad name are filtered out so we don't recommend re-activating the wrong region.
"""
from __future__ import annotations

import datetime as dt
import math
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


def _region_tag(name: str) -> str:
    s = name.strip()
    if s.startswith("[SG]") or s.startswith("MARTIN-SG") or "SG " in s[:8]:
        return "SG"
    if s.startswith("[BRUNEI]") or "BRUNEI" in s[:10].upper():
        return "BR"
    if s.startswith("[MY]") or s.startswith("MARTIN-MY"):
        return "MY"
    return "??"


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

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
    date_col = cols.get("date", -1)

    date_hdr = repr(header[date_col]) if date_col >= 0 else "NONE"
    phone_hdr = repr(header[phone_col]) if phone_col >= 0 else "NONE"
    print(f"Sheet '{s.cpa.sales_tab}'  ·  header row #{header_idx}  ·  "
          f"data rows: {len(values) - header_idx - 1}")
    print(f"Date column: #{date_col} ({date_hdr})")
    print(f"Phone column: #{phone_col} ({phone_hdr})")
    print("Full header (for triage):")
    for i, h in enumerate(header):
        print(f"   col {i:>2}: {h!r}")

    # Re-scan for a date column that includes Chinese / other non-English
    # headers, since cpa.find_columns only knows 'createddate'/'date'.
    if date_col == -1:
        DATE_HINTS = ("date", "日期", "時間", "时间", "created", "purchase",
                      "订单日期", "報名日期", "报名日期", "購買日期", "购买日期")
        for i, h in enumerate(header):
            hs = (h or "").casefold()
            if any(hint in hs for hint in DATE_HINTS):
                date_col = i
                print(f"  → picked date column #{i} = {h!r} by keyword scan")
                break
        # Fallback: try to sniff by peeking at data — column with the highest
        # ratio of parseable dates in the first 100 rows.
        if date_col == -1:
            best_i, best_hits = -1, 0
            sample = values[header_idx + 1:header_idx + 101]
            for i in range(len(header)):
                hits = sum(1 for row in sample
                           if i < len(row) and cpa.parse_date(row[i]))
                if hits > best_hits:
                    best_i, best_hits = i, hits
            if best_hits > 5:
                date_col = best_i
                print(f"  → sniffed date column #{best_i} "
                      f"({header[best_i]!r}) — {best_hits}/100 rows parse")
            else:
                print("  → no date column detected even after keyword + sniff")

        # Propagate the detected date column into cpa.parse_sales: force its
        # find_columns() to pick this column by rewriting the header cell.
        if date_col >= 0:
            values[header_idx][date_col] = "date"
            header = values[header_idx]

    # Filter to SG rows AND dump a date-parseability diagnostic on SG rows.
    sg_rows = [header]
    date_parseable = 0
    date_blank = 0
    date_unparseable_samples = []
    for row in values[header_idx + 1:]:
        phone_raw = row[phone_col] if 0 <= phone_col < len(row) else ""
        if not _is_sg(phone_raw):
            continue
        sg_rows.append(row)
        raw = row[date_col] if 0 <= date_col < len(row) else ""
        if not raw:
            date_blank += 1
        elif cpa.parse_date(raw):
            date_parseable += 1
        else:
            if len(date_unparseable_samples) < 5:
                date_unparseable_samples.append(raw)
    sg_total = len(sg_rows) - 1
    print(f"\nSG rows (phone starts with 65): {sg_total}")
    print(f"  · dates parseable: {date_parseable}"
          f"  · blank: {date_blank}"
          f"  · un-parseable: {sg_total - date_parseable - date_blank}")
    if date_unparseable_samples:
        print(f"  · un-parseable date samples: {date_unparseable_samples}")

    sales, _c, _h = cpa.parse_sales(sg_rows, s.cpa.price_myr)

    # Attribute per (ad name) with 30d / 90d / lifetime buckets.
    cutoff_30 = today - dt.timedelta(days=30)
    cutoff_90 = today - dt.timedelta(days=90)
    d30 = defaultdict(int)
    d90 = defaultdict(int)
    lifetime = defaultdict(int)
    life_rev = defaultdict(float)
    for sale in sales:
        if not sale.ad:
            continue
        lifetime[sale.ad] += 1
        life_rev[sale.ad] += sale.amount
        if sale.date:
            if sale.date > cutoff_30:
                d30[sale.ad] += 1
            if sale.date > cutoff_90:
                d90[sale.ad] += 1

    # Pick the freshest bucket that has any signal, so we can still answer if
    # dates are patchy.
    if sum(d30.values()) > 0:
        window, window_name = d30, "30d"
    elif sum(d90.values()) > 0:
        window, window_name = d90, "90d (fallback: 30d bucket was empty)"
    else:
        window, window_name = lifetime, "lifetime (fallback: 30d/90d empty)"

    top_recent = sorted(window.items(), key=lambda kv: -kv[1])
    total_recent = sum(v for _, v in top_recent)
    print(f"\nRecency window used: {window_name}  ·  total SG sales in window: "
          f"{total_recent}  ·  distinct ad names: {sum(1 for _, v in top_recent if v > 0)}")
    print("Top ad names in window (SG only):")
    for name, cnt in top_recent[:15]:
        if cnt <= 0:
            break
        print(f"   {cnt:>3}  ·  {name[:66]}")

    # Pull all Meta ads + lifetime per-ad spend.
    g = graph_client(s)
    acct = s.meta.account_path
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,effective_status,created_time,"
                  "campaign{name,effective_status},"
                  "adset{name,effective_status}",
        "limit": 500,
    })
    spend_by_id = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", date_preset="maximum")}

    # Candidates: PAUSED Meta ad, in an SG-tagged campaign, whose name has
    # any window sales, and whose ROAS > 1 (or 0 spend).
    tiers = cpa.CpaTiers(s.cpa.healthy_max_myr, s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr)
    candidates = []
    for ad in ads:
        if ad.get("effective_status") == "ACTIVE":
            continue
        camp = (ad.get("campaign") or {}).get("name", "")
        if _region_tag(camp) != "SG":
            continue
        name = ad.get("name", ad["id"])
        key = cpa.norm(name)
        recent = window.get(key, 0)
        if recent < 1:
            continue
        rev = life_rev.get(key, 0.0)
        spend = spend_by_id.get(ad["id"], 0.0)
        roas = (rev / spend) if spend > 0 else math.inf
        if roas <= 1.0:
            continue
        life = lifetime.get(key, 0)
        cpa_val = cpa.cpa(spend, life)
        created = cpa.parse_date((ad.get("created_time") or "")[:10])
        age = (today - created).days if created else None
        candidates.append({
            "ad_id": ad["id"], "name": name, "camp": camp,
            "adset": (ad.get("adset") or {}).get("name", ""),
            "status": ad.get("effective_status"),
            "camp_status": (ad.get("campaign") or {}).get("effective_status"),
            "adset_status": (ad.get("adset") or {}).get("effective_status"),
            "recent": recent, "life": life, "rev": rev, "spend": spend,
            "roas": roas, "cpa": cpa_val, "age": age,
        })

    candidates.sort(key=lambda c: (-c["recent"], -c["roas"]))

    print(f"\nSG paused-and-worth-scaling  ·  window={window_name}  ·  "
          f"{len(candidates)} candidate variants (region=SG only)")
    if not candidates:
        print("(nothing meets the filters — either no SG paused ads had window sales, "
              "or every match has ROAS ≤ 1)")
        return

    print(f"\n{'#':>2} {'ad_id':>18} {'st':>16} {'recent':>6} {'life':>4} "
          f"{'rev':>8} {'spend':>7} {'ROAS':>6} {'CPA':>6} {'age':>5}  ad name")
    print("-" * 128)
    for i, c in enumerate(candidates, 1):
        cpa_str = "—" if c["cpa"] is None else ("∞" if c["cpa"] == math.inf else f"{c['cpa']:.0f}")
        roas_str = "∞" if c["roas"] == math.inf else f"{c['roas']:.1f}"
        age_str = "—" if c["age"] is None else f"{c['age']}d"
        print(f"{i:>2} {c['ad_id']:>18} {c['status']:>16} {c['recent']:>6} "
              f"{c['life']:>4} {c['rev']:>8,.0f} {c['spend']:>7,.0f} {roas_str:>6} "
              f"{cpa_str:>6} {age_str:>5}  {c['name'][:44]}")

    print("\nParent status (flip parents ACTIVE too when they are PAUSED):")
    for c in candidates:
        marks = []
        if c["camp_status"] != "ACTIVE":
            marks.append(f"campaign {c['camp_status']}")
        if c["adset_status"] != "ACTIVE":
            marks.append(f"ad set {c['adset_status']}")
        marks = ", ".join(marks) if marks else "parents ACTIVE — flipping the ad alone is enough"
        print(f"  · {c['ad_id']}  {c['name'][:44]:44}  →  {marks}")


if __name__ == "__main__":
    main()
