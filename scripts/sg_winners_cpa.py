"""SG winners CPA — join SG paid sales (phone +65) to SG-account spend → CPA per ad name.

Accuracy model:
  · SG sales  = rows whose WhatsApp number starts with +65 (definitively Singapore),
                counted per UTM ad name, windowed 30d / 60d / this-quarter (Jun 1 →).
  · SG spend  = Meta spend in the SG account (act_1024930575770087) grouped by ad name,
                EXCLUDING [BRUNEI] campaigns (this account is SG + a little Brunei; MY is a
                separate account, so it never contaminates). Windowed 30d / 60d.
  · CPA       = SG spend ÷ SG sales, per ad name, in each window.
Also reports, per winning creative, how many Meta copies exist and whether ANY is ACTIVE
right now — so paused winners surface as reopen candidates. Classified vs the operator KPI
(target 740 / acceptable 1040 / hard-stop 1300). Read-only, no writes.
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
    "whatsapp", "wa", "wsn", "whatsappnumber", "hp", "handphone",
)
DATE_HDRS = ("报名日期", "報名日期", "date", "日期", "报名", "報名", "成交日期", "付款日期", "购买日期", "createddate")
QUARTER_START = dt.date(2026, 6, 1)


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


def _sg_phone(raw: str) -> bool:
    return re.sub(r"[^\d+]", "", raw or "").lstrip("+").startswith("65")


def _is_brunei(camp: str) -> bool:
    c = (camp or "").strip().lower()
    return c.startswith("[brunei]") or "brunei" in c[:14]


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    return "—" if v is None else ("∞" if v == math.inf else f"{v:.0f}")


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)
    tgt, acc, hard = s.cpa.target_myr, s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    # ── 1. SG sales (phone +65) per ad name, windowed ───────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    hdr_idx, cols = 0, cpa.find_columns(values[0] if values else [])
    for i, row in enumerate(values[:8]):
        c = cpa.find_columns(row)
        if c.get("ad", -1) >= 0 and c.get("campaign", -1) >= 0:
            hdr_idx, cols = i, c
            break
    header = values[hdr_idx]
    phone_col = _find_phone_col(header)
    date_col = cols.get("date", -1)
    if date_col < 0:
        date_col = _find_col_loose(header, DATE_HDRS)
    ad_col = cols.get("ad", -1)
    if phone_col < 0 or date_col < 0 or ad_col < 0:
        raise SystemExit(f"‼️ column detect failed (phone={phone_col} date={date_col} ad={ad_col})")

    def cell(row, i):
        return row[i] if 0 <= i < len(row) else ""

    s30, s60, sq = defaultdict(int), defaultdict(int), defaultdict(int)
    disp = {}
    for row in values[hdr_idx + 1:]:
        if not _sg_phone(cell(row, phone_col)):
            continue
        name = cpa.norm(cell(row, ad_col))
        if not name:
            continue
        key = cpa.ad_key(name)
        disp.setdefault(key, name)
        d = cpa.parse_date(cell(row, date_col))
        if not d:
            continue
        if d > d30:
            s30[key] += 1
        if d > d60:
            s60[key] += 1
        if d >= QUARTER_START:
            sq[key] += 1

    # ── 2. SG-account spend per ad name (exclude Brunei) + live status ───────────
    g = graph_client(s)
    acct = s.meta.account_path
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,effective_status,campaign{name}", "limit": 500})
    sp30 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend",
        time_range={"since": d30.isoformat(), "until": today.isoformat()})}
    sp60 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend",
        time_range={"since": d60.isoformat(), "until": today.isoformat()})}

    spend30, spend60 = defaultdict(float), defaultdict(float)
    copies, active_copies, brunei_skipped = defaultdict(int), defaultdict(int), 0
    for ad in ads:
        camp = (ad.get("campaign") or {}).get("name", "")
        if _is_brunei(camp):
            brunei_skipped += 1
            continue
        key = cpa.ad_key(ad.get("name", ""))
        spend30[key] += sp30.get(ad["id"], 0.0)
        spend60[key] += sp60.get(ad["id"], 0.0)
        copies[key] += 1
        if ad.get("effective_status") == "ACTIVE":
            active_copies[key] += 1

    # ── 3. Leaderboard over creatives with real SG sales (60d) ──────────────────
    keys = sorted({k for k in s60 if s60[k] > 0}, key=lambda k: -s60[k])
    print(f"SG WINNERS CPA  ·  {today}  ·  SG sales = phone +65 · SG spend = SG account "
          f"(act ...{acct[-6:]}) minus [BRUNEI]  ·  Brunei ads skipped: {brunei_skipped}")
    print(f"KPI: target RM{tgt:.0f} · acceptable RM{acc:.0f} · hard-stop RM{hard:.0f}\n")
    hdr = (f"{'ad name':40}|{'60d sale':>8}|{'60d sp':>8}|{'CPA60':>7}|"
           f"{'30d sale':>8}|{'30d sp':>7}|{'CPA30':>7}|{'copies(live)':>12}|verdict")
    print(hdr)
    print("-" * len(hdr))
    for k in keys:
        c60 = cpa.cpa(spend60[k], s60[k])
        c30 = cpa.cpa(spend30[k], s30[k])
        live = active_copies.get(k, 0)
        ncopy = copies.get(k, 0)
        # verdict
        if ncopy == 0:
            v = "⚠️ no Meta ad by this name (UTM mismatch?)"
        elif live == 0:
            v = "💤 REOPEN — winner but 0 ACTIVE copy"
        elif c60 is None:
            v = "· no recent spend"
        elif c60 == math.inf:
            v = "🔴 spend, 0 sale in 60d"
        elif c60 <= tgt:
            v = "🟢 SCALE — CPA ≤ target"
        elif c60 <= acc:
            v = "🟢 KEEP/scale-careful — CPA ≤ acceptable"
        elif c60 <= hard:
            v = "🟡 WATCH — CPA in 1040–1300"
        else:
            v = "🔴 EXPENSIVE — CPA > hard-stop"
        print(f"{disp[k][:40]:40}|{s60[k]:>8}|{spend60[k]:>8.0f}|{_s(c60):>7}|"
              f"{s30[k]:>8}|{spend30[k]:>7.0f}|{_s(c30):>7}|{f'{ncopy}({live})':>12}|{v}")

    # totals
    tot_s60 = sum(s60.values())
    tot_sp60 = sum(spend60[k] for k in s60)
    blended = cpa.cpa(tot_sp60, tot_s60)
    print("\n" + "─" * 70)
    print(f"60d SG sales (matched to a named ad): {tot_s60}  ·  SG spend on those names: "
          f"RM{tot_sp60:,.0f}  ·  blended CPA RM{_s(blended)}")
    print("Note: sales counted by +65 phone; a creative's spend sums all its SG copies "
          "(incl. now-paused ones that spent in-window). CPA≈0 rows = sold but the current "
          "copy barely spent (sale likely via a paused copy → see 💤).")


if __name__ == "__main__":
    main()
