"""Read-only: SG paid sales for June / July / August 2026, with the converting ads.

SG isolation = phone country code **+65** (the proven, operator-accepted signal — a +65
buyer is definitively Singapore; the UTM "[sg]" marker is looser and older SG campaigns
lack it). Every number is cross-checked against the campaign-name [sg]/martin-sg marker so
the two SG signals can be compared for confidence.

Source tab: the operator-linked gid (1500782859) if it resolves to a real sales list
(has UTM ad + campaign columns); otherwise the configured sales_tab. All tabs + gids are
printed so the linked gid is identifiable. Accuracy diagnostics (signal agreement, phone
prefix histogram, full month coverage, undated rows) are printed before the answer.

Per target month prints: SG sale count · revenue (sheet Amount as-is) · the ADS that
converted those SG buyers (ranked) · the campaigns. No writes, no Meta calls.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.drive import build_credentials
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings

LINKED_GID = 1500782859


def _month_back(d: dt.date, n: int):
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    return (y, m)


# auto-roll: the current month + the 2 prior, computed at run time (reusable month to month)
_TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
TARGET = [_month_back(_TODAY, 2), _month_back(_TODAY, 1), (_TODAY.year, _TODAY.month)]

PHONE_HEADERS = (
    "phone", "phonenumber", "phoneno", "mobile", "mobilenumber", "mobileno",
    "contact", "contactnumber", "contactno", "tel", "telephone",
    "whatsapp", "wa", "wsn", "whatsappnumber", "hp", "handphone",
)
DATE_HDRS = ("报名日期", "報名日期", "date", "日期", "报名", "報名", "成交日期", "付款日期", "购买日期", "createddate")


def _hkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def _find_phone_col(header) -> int:
    keys = [_hkey(h) for h in header]
    for needle in PHONE_HEADERS:
        for i, k in enumerate(keys):
            if k == needle:
                return i
    for needle in ("phone", "mobile", "whatsapp", "contact", "hp"):
        for i, k in enumerate(keys):
            if needle in k:
                return i
    return -1


def _find_col_loose(header, needles) -> int:
    low = [(h or "").strip().lower() for h in header]
    for n in needles:
        for i, h in enumerate(low):
            if n in h:
                return i
    return -1


def _sniff_date_col(rows, hdr_idx, ncols) -> int:
    best, best_hits = -1, 0
    for c in range(ncols):
        hits = sum(1 for row in rows[hdr_idx + 1: hdr_idx + 121]
                   if c < len(row) and cpa.parse_date(row[c]))
        if hits > best_hits:
            best, best_hits = c, hits
    return best if best_hits >= 10 else -1


def _sg_phone(raw: str) -> bool:
    p = re.sub(r"[^\d+]", "", raw or "").lstrip("+")
    return p.startswith("65")


def _sg_campaign(camp: str) -> bool:
    c = (camp or "").lower()
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def _tabs_meta(sa_json: str, sid: str):
    from googleapiclient.discovery import build  # lazy
    svc = build("sheets", "v4", credentials=build_credentials(sa_json), cache_discovery=False)
    meta = svc.spreadsheets().get(
        spreadsheetId=sid, fields="sheets.properties(sheetId,title,gridProperties)").execute()
    return [(p["properties"]["sheetId"], p["properties"].get("title", "")) for p in meta.get("sheets", [])]


def _detect(values):
    """Header row + column map for a sales tab. Returns (hdr_idx, cols, phone_col, date_col)."""
    hdr_idx, cols = 0, cpa.find_columns(values[0] if values else [])
    for i, row in enumerate(values[:8]):
        c = cpa.find_columns(row)
        if c.get("ad", -1) >= 0 and c.get("campaign", -1) >= 0:
            hdr_idx, cols = i, c
            break
    header = values[hdr_idx] if values else []
    ncols = max((len(r) for r in values[hdr_idx:hdr_idx + 80]), default=0)
    phone_col = _find_phone_col(header)
    date_col = cols.get("date", -1)
    if date_col < 0:
        date_col = _find_col_loose(header, DATE_HDRS)
    if date_col < 0:
        date_col = _sniff_date_col(values, hdr_idx, ncols)
    return hdr_idx, cols, phone_col, date_col


def main() -> None:
    s = load_settings()
    sid = s.cpa.spreadsheet_id
    sc = SheetsClient(s.secrets.google_sa_json)

    tabs = _tabs_meta(s.secrets.google_sa_json, sid)
    print(f"Spreadsheet {sid}")
    print("Tabs (gid · title):")
    for gid, title in tabs:
        mark = "  ← LINKED" if gid == LINKED_GID else ("  (config sales_tab)" if title == s.cpa.sales_tab else "")
        print(f"   {gid:>12} · {title!r}{mark}")
    linked_title = next((t for g, t in tabs if g == LINKED_GID), None)
    print(f"\nLinked gid {LINKED_GID} resolves to tab: {linked_title!r}")

    # choose source: linked tab if it's a real sales list, else config sales_tab
    chosen, values, why = None, None, ""
    if linked_title:
        v = sc.read_tab(sid, linked_title)
        hdr_idx, cols, phone_col, date_col = _detect(v)
        if cols.get("ad", -1) >= 0 and phone_col >= 0:
            chosen, values, why = linked_title, v, "linked gid is a valid sales list (has UTM ad + phone)"
        else:
            why = (f"linked tab {linked_title!r} lacks ad/phone columns "
                   f"(ad={cols.get('ad',-1)}, phone={phone_col}) → fell back to config sales_tab")
    if chosen is None:
        chosen = s.cpa.sales_tab
        values = sc.read_tab(sid, chosen)
        if not why:
            why = "using config sales_tab"
    hdr_idx, cols, phone_col, date_col = _detect(values)
    ad_col, adset_col, camp_col, amt_col = (cols.get("ad", -1), cols.get("adset", -1),
                                            cols.get("campaign", -1), cols.get("amount", -1))
    header = values[hdr_idx]

    print(f"\nUsing tab: {chosen!r}   ({why})")
    print(f"header row #{hdr_idx}: {[ (h or '')[:16] for h in header[:22] ]}")
    print(f"cols → date={date_col} ad={ad_col} adset={adset_col} campaign={camp_col} "
          f"amount={amt_col} phone={phone_col}")
    if phone_col < 0:
        print("\n‼️  NO PHONE COLUMN FOUND — cannot isolate SG by +65. Aborting to avoid a wrong answer.")
        raise SystemExit(1)
    if date_col < 0:
        print("\n‼️  NO DATE COLUMN FOUND — cannot bucket by month. Aborting to avoid a wrong answer.")
        raise SystemExit(1)
    print(f"date header={header[date_col]!r}  phone header={header[phone_col]!r}")
    print(f"date samples={[r[date_col] for r in values[hdr_idx+1:hdr_idx+4] if date_col < len(r)]}\n")

    def cell(row, i):
        return row[i] if 0 <= i < len(row) else ""

    total = sg_phone = sg_camp = both = undated_sg = 0
    prefix_hist = defaultdict(int)
    all_months = defaultdict(int)              # (y,mo) -> SG-by-phone count
    month_rows = defaultdict(list)             # (y,mo) -> [(ad, camp, adset, amt, date)]

    for row in values[hdr_idx + 1:]:
        ad = cpa.norm(cell(row, ad_col)) if ad_col >= 0 else ""
        camp = cpa.norm(cell(row, camp_col)) if camp_col >= 0 else ""
        phone_raw = cell(row, phone_col)
        # a data row needs at least a phone or a UTM value (skip blank spacer rows)
        if not ad and not camp and not re.search(r"\d", phone_raw or ""):
            continue
        total += 1
        p = re.sub(r"[^\d+]", "", phone_raw or "").lstrip("+")
        prefix_hist[p[:2] or "(blank)"] += 1
        sgp, sgc = p.startswith("65"), _sg_campaign(camp)
        sg_phone += sgp
        sg_camp += sgc
        both += (sgp and sgc)
        if not sgp:
            continue
        d = cpa.parse_date(cell(row, date_col))
        if d is None:
            undated_sg += 1
            continue
        amt = cpa._money(cell(row, amt_col), 0.0) if amt_col >= 0 else 0.0
        all_months[(d.year, d.month)] += 1
        month_rows[(d.year, d.month)].append(
            (ad, camp, cpa.norm(cell(row, adset_col)) if adset_col >= 0 else "", amt, d))

    print("── ACCURACY CROSS-CHECK ──────────────────────────────────────────────")
    print(f"total data rows           : {total}")
    print(f"SG by phone +65 (PRIMARY) : {sg_phone}")
    print(f"SG by campaign [sg] marker: {sg_camp}")
    print(f"both signals on same row  : {both}   (overlap check)")
    print(f"SG-phone rows undated     : {undated_sg}  (excluded from month buckets)")
    print("phone country-prefix histogram (first 2 digits, top 14):")
    for pfx, n in sorted(prefix_hist.items(), key=lambda kv: -kv[1])[:14]:
        tag = " ← SG" if pfx == "65" else (" ← MY" if pfx == "60" else "")
        print(f"     {pfx:>8} : {n}{tag}")
    print("\nAll months present (SG by phone +65):")
    for k in sorted(all_months):
        star = "  ★" if k in TARGET else ""
        print(f"     {k[0]}-{k[1]:02d} : {all_months[k]}{star}")

    grand = 0
    grand_rev = 0.0
    for key in TARGET:
        rows = month_rows.get(key, [])
        y, mo = key
        rev = sum(r[3] for r in rows)
        grand += len(rows)
        grand_rev += rev
        print("\n" + "=" * 72)
        print(f" {y}-{mo:02d}  ·  SG paid sales: {len(rows)}  ·  revenue (sheet Amount): RM{rev:,.0f}")
        print("=" * 72)
        if not rows:
            print("   (no SG sales this month)")
            continue
        per_ad, per_camp = defaultdict(int), defaultdict(int)
        for ad, camp, adset, amt, d in rows:
            per_ad[ad or "(blank ad name)"] += 1
            per_camp[camp or "(blank campaign)"] += 1
        print(f" Converting ADS ({len(per_ad)} distinct) — by SG sale count:")
        for ad, n in sorted(per_ad.items(), key=lambda kv: -kv[1]):
            print(f"   {n:>3}  {ad[:64]}")
        print(f" Converting CAMPAIGNS ({len(per_camp)} distinct):")
        for c, n in sorted(per_camp.items(), key=lambda kv: -kv[1]):
            print(f"   {n:>3}  {c[:64]}")

    print("\n" + "─" * 72)
    print(f" TOTAL Jun+Jul+Aug 2026 SG paid sales: {grand}  ·  revenue RM{grand_rev:,.0f}")
    print(f" SG signal = phone +65. Cross-check vs campaign-[sg] marker printed above.")


if __name__ == "__main__":
    main()
