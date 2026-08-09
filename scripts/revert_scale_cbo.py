"""See what's really inside Scale-CBO (hyphen-robust match) AND revert its budget to RM200.

The earlier throttle cut Scale-CBO −40% (RM200→120) to slow 我不会买牛奶, but the inspect filter
missed the campaign (non-ASCII hyphen) so its other ads were never verified. Scale-CBO is a
deliberate scale campaign with real sales, so per "don't touch the good ones" we restore it to
RM200 and print every ad's 7d CPL + 60d SG ROAS so the operator can see exactly what's in it.
LIVE (one budget write); everything else read-only.
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
RESTORE_CENTS = 20000  # RM200/day
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

    # locate the Scale-CBO campaign (hyphen-robust)
    camp = None
    for a in ads:
        c = a.get("campaign") or {}
        if "scale-cbo" in _norm_hyphen(c.get("name", "")).lower():
            camp = c
            break
    if not camp:
        log.warning("No Scale-CBO campaign found — nothing to revert.")
        return
    cid, cname = camp["id"], camp.get("name", "")
    cur = int(camp["daily_budget"]) if camp.get("daily_budget") else None
    log.info("Scale-CBO = %r (id %s) · current budget %s",
             cname, cid, f"RM{cur/100:.0f}" if cur else "—(not CBO?)")

    members = [a for a in ads if (a.get("campaign") or {}).get("id") == cid]
    log.info("─ ads in Scale-CBO (status/effective · 7d CPL · 60d SG ROAS):")
    any_good = False
    for a in members:
        w = ins7.get(a["id"]) or {}
        sp7, rg7 = _f(w.get("spend")), extract_results(w.get("actions"), token)
        cpl7 = (sp7 / rg7) if rg7 > 0 else (math.inf if sp7 > 0 else None)
        k = cpa.ad_key(a.get("name", ""))
        ro = roas(k)
        good = ((cpl7 is not None and cpl7 != math.inf and cpl7 <= s.kpi.cpl_threshold_myr) or
                (ro is not None and ro >= 2.0))
        any_good = any_good or (good and a.get("effective_status") == "ACTIVE")
        cpl_s = "—" if cpl7 is None else ("∞" if cpl7 == math.inf else f"{cpl7:.0f}")
        ro_s = "—" if ro is None else f"{ro:.2f}x"
        log.info("   %-13s %-30s stat=%s/%s 7d RM%.0f/%dreg CPL %s · ROAS %s",
                 "🟢 GOOD" if good else "🔴 weak", (a.get("name") or "")[:30],
                 a.get("status"), a.get("effective_status"), sp7, rg7, cpl_s, ro_s)

    if cur is None:
        log.warning("Scale-CBO has no campaign daily_budget (ABO?) — nothing to revert.")
        return
    if cur >= RESTORE_CENTS:
        log.info("Budget already ≥ RM200 — no revert needed.")
    else:
        g._request("POST", cid, data={"daily_budget": str(RESTORE_CENTS)})
        log.info("✓ REVERTED Scale-CBO budget RM%.0f → RM%.0f/day", cur / 100, RESTORE_CENTS / 100)

    final_summary(log, f"Scale-CBO restored to RM200 (protect its ads) — good ads present: {any_good}. "
                       f"我不会买牛奶 lives here; it can only be cut by pausing its own copy (you said 不关) "
                       f"→ left running, flag for the ~1-week CPA review. Parents 3–17 throttle kept (all weak).")


if __name__ == "__main__":
    main()
