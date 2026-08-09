"""Definitively fix BOTH Scale-CBO campaigns after a mis-targeted revert.

State to fix:
  · 'MARTIN-SG | Scale-CBO'   — the one throttled RM200→120 (holds 我不会买牛奶 copy 120256123439210093
                                + 2 live siblings). Never properly inspected.
  · 'MARTIN-SG | Scale-CBO 2' — accidentally raised RM100→200 by a first-match bug; all its ads PAUSED.

Actions:
  · Scale-CBO 2  → restore to RM100 (undo the accidental raise).
  · real Scale-CBO (campaign of copy 120256123439210093, else the scale-cbo campaign not ending in "2"):
      revert to RM200 IF it holds any ACTIVE good ad (60d SG ROAS ≥ 2 or 7d CPL ≤ 65); else keep RM120.
Prints every ad in each scale-cbo campaign with 7d CPL + 60d SG ROAS. LIVE budget writes only.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

PRICE = 2591.0
WNBW_COPY = "120256123439210093"        # 我不会买牛奶 heavy copy → identifies the REAL Scale-CBO
RM100, RM200 = 10000, 20000
PHONE_HEADERS = ("phone", "phonenumber", "mobile", "whatsapp", "contact", "hp", "handphone", "wsn")


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _hkey(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def _norm_hyphen(s):
    return re.sub(r"[‐-―−]", "-", s or "")


def _phone_col(header):
    keys = [_hkey(h) for h in header]
    for n in PHONE_HEADERS:
        for i, k in enumerate(keys):
            if k == n or n in k:
                return i
    return -1


def _sg(raw):
    return re.sub(r"[^\d+]", "", raw or "").lstrip("+").startswith("65")


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d7 = (today - dt.timedelta(days=7)).isoformat()
    d60 = (today - dt.timedelta(days=60)).isoformat()
    token = result_action_type(s.meta.conversion_event)
    ceil = s.kpi.cpl_threshold_myr

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    hi, cols = 0, cpa.find_columns(values[0] if values else [])
    for i, row in enumerate(values[:8]):
        c = cpa.find_columns(row)
        if c.get("ad", -1) >= 0 and c.get("campaign", -1) >= 0:
            hi, cols = i, c
            break
    header = values[hi]
    pcol, dcol, adcol = _phone_col(header), cols.get("date", -1), cols.get("ad", -1)
    s60 = defaultdict(int)
    for row in values[hi + 1:]:
        ph = row[pcol] if 0 <= pcol < len(row) else ""
        if not _sg(ph):
            continue
        nm = cpa.norm(row[adcol]) if 0 <= adcol < len(row) else ""
        d = cpa.parse_date(row[dcol]) if 0 <= dcol < len(row) else None
        if nm and d and d.isoformat() >= d60:
            s60[cpa.ad_key(nm)] += 1

    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,campaign{id,name,daily_budget}", "limit": 500})
    ins7 = {r.get("ad_id"): r for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend,actions", time_range={"since": d7, "until": today.isoformat()})}
    sp60_by_ad = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", time_range={"since": d60, "until": today.isoformat()})}
    spend60 = defaultdict(float)
    for a in ads:
        spend60[cpa.ad_key(a.get("name", ""))] += sp60_by_ad.get(a["id"], 0.0)

    def roas(k):
        sp = spend60.get(k, 0.0)
        return (PRICE * s60.get(k, 0)) / sp if sp > 0 and s60.get(k, 0) > 0 else None

    # all scale-cbo campaigns
    camps = {}
    real_id = None
    for a in ads:
        c = a.get("campaign") or {}
        if "scale-cbo" in _norm_hyphen(c.get("name", "")).lower():
            camps[c["id"]] = c
            if a["id"] == WNBW_COPY:
                real_id = c["id"]
    if real_id is None:  # fallback: the scale-cbo campaign whose name does not end in "2"
        for cid, c in camps.items():
            if not _norm_hyphen(c.get("name", "")).strip().endswith("2"):
                real_id = cid
                break
    log.info("scale-cbo campaigns found: %d · real=%s", len(camps), real_id)
    summary = []

    for cid, c in camps.items():
        cname = c.get("name", "")
        cur = int(c["daily_budget"]) if c.get("daily_budget") else None
        members = [a for a in ads if (a.get("campaign") or {}).get("id") == cid]
        log.info("═" * 88)
        log.info("%r (id %s) · budget %s · %d ads", cname, cid,
                 f"RM{cur/100:.0f}" if cur else "—", len(members))
        active_good = False
        for a in members:
            w = ins7.get(a["id"]) or {}
            sp7, rg7 = _f(w.get("spend")), extract_results(w.get("actions"), token)
            cpl7 = (sp7 / rg7) if rg7 > 0 else (math.inf if sp7 > 0 else None)
            k = cpa.ad_key(a.get("name", ""))
            ro = roas(k)
            good = ((cpl7 is not None and cpl7 != math.inf and cpl7 <= ceil) or (ro is not None and ro >= 2.0))
            if good and a.get("effective_status") == "ACTIVE":
                active_good = True
            log.info("   %-8s %-30s %s/%s 7dRM%.0f/%dreg CPL %s · ROAS %s",
                     "🟢GOOD" if good else "🔴weak", (a.get("name") or "")[:30],
                     a.get("status"), a.get("effective_status"), sp7, rg7,
                     "—" if cpl7 is None else ("∞" if cpl7 == math.inf else f"{cpl7:.0f}"),
                     "—" if ro is None else f"{ro:.2f}x")
        if cur is None:
            summary.append(f"{cname[:24]}: no CBO budget — skipped")
            continue
        if cid == real_id:
            if active_good and cur < RM200:
                g._request("POST", cid, data={"daily_budget": str(RM200)})
                summary.append(f"{cname[:24]}: has ACTIVE good ad → REVERTED RM{cur/100:.0f}→RM200")
                log.info("   ✓ has ACTIVE good ad → revert to RM200")
            elif not active_good:
                summary.append(f"{cname[:24]}: all ACTIVE ads weak → KEEP throttle RM{cur/100:.0f}")
                log.info("   ✓ all active ads weak → keep throttle RM%.0f", cur / 100)
            else:
                summary.append(f"{cname[:24]}: already ≥RM200 — left")
        else:  # Scale-CBO 2 (or any other) — undo the accidental raise to RM100
            if cur != RM100:
                g._request("POST", cid, data={"daily_budget": str(RM100)})
                summary.append(f"{cname[:24]}: restored RM{cur/100:.0f}→RM100 (undo accidental change)")
                log.info("   ✓ restored to RM100")
            else:
                summary.append(f"{cname[:24]}: already RM100 — left")

    log.info("═" * 88)
    for line in summary:
        log.info("  • %s", line)
    final_summary(log, "Scale-CBO campaigns reconciled. Parents 3–17 throttle kept (all weak). "
                       "我不会买牛奶 sits in the real Scale-CBO; if that campaign was kept throttled it "
                       "means all its active ads are weak. Fuller CPA read due ~1 week out.")


if __name__ == "__main__":
    main()
