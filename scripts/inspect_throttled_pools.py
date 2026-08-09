"""Read-only: inspect the two campaigns just throttled (Scale-CBO, Parents 3–17 + Engaged) —
list every ACTIVE ad with its 7d CPL and its creative's 60d SG CPA/ROAS, so we can tell which
ads in those shared CBOs are actually GOOD (and were unfairly caught by the −40% budget cut).

CPL7 = 7d spend ÷ 7d complete-registrations (Meta). ROAS = RM2,591 × 60d SG sales ÷ 60d SG
spend for that creative name (SG sales = +65 phone). Verdict flags good vs weak. No writes.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

PRICE = 2591.0
PHONE_HEADERS = ("phone", "phonenumber", "mobile", "whatsapp", "contact", "hp", "handphone", "wsn")
TARGETS = ("scale-cbo", "parents 3")   # campaign-name substrings (lowercased) that I throttled


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _hkey(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


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
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d7 = (today - dt.timedelta(days=7)).isoformat()
    d60 = (today - dt.timedelta(days=60)).isoformat()
    token = result_action_type(s.meta.conversion_event)

    # SG sales (60d) + SG spend (60d) per creative name
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
        "fields": "id,name,effective_status,campaign{id,name,daily_budget}", "limit": 500})
    ins7 = {r.get("ad_id"): r for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend,actions", time_range={"since": d7, "until": today.isoformat()})}
    sp60 = defaultdict(float)
    for r in g.account_insights(acct, level="ad", fields="ad_id,spend",
                                time_range={"since": d60, "until": today.isoformat()}):
        pass  # per-name 60d spend needs ad→name; do below

    sp60_by_ad = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", time_range={"since": d60, "until": today.isoformat()})}
    spend60 = defaultdict(float)
    for a in ads:
        spend60[cpa.ad_key(a.get("name", ""))] += sp60_by_ad.get(a["id"], 0.0)

    def roas(name_key):
        sp = spend60.get(name_key, 0.0)
        return (PRICE * s60.get(name_key, 0)) / sp if sp > 0 and s60.get(name_key, 0) > 0 else None

    print(f"THROTTLED-POOL INSPECT · {today} · CPL7=7d · ROAS=60d SG(+65)·RM2591 · ceiling RM65\n")
    for a in ads:
        camp = (a.get("campaign") or {})
        cname = camp.get("name", "")
        if not any(t in cname.lower() for t in TARGETS):
            continue
        if a.get("effective_status") != "ACTIVE":
            continue
        w = ins7.get(a["id"]) or {}
        spend7, reg7 = _f(w.get("spend")), extract_results(w.get("actions"), token)
        cpl7 = (spend7 / reg7) if reg7 > 0 else (math.inf if spend7 > 0 else None)
        k = cpa.ad_key(a.get("name", ""))
        ro = roas(k)
        good = ((cpl7 is not None and cpl7 != math.inf and cpl7 <= s.kpi.cpl_threshold_myr) or
                (ro is not None and ro >= 2.0))
        cpl_s = "—" if cpl7 is None else ("∞" if cpl7 == math.inf else f"{cpl7:.0f}")
        ro_s = "—" if ro is None else f"{ro:.2f}x"
        bud = camp.get("daily_budget")
        bud_s = f"RM{int(bud)/100:.0f}" if bud else "—"
        flag = "🟢 GOOD—leave" if good else "🔴 weak"
        print(f"{flag:16}| {(a.get('name') or '')[:34]:34} | 7d RM{spend7:>5.0f}/{reg7:>2}reg CPL {cpl_s:>4} "
              f"| ROAS {ro_s:>6} | camp {cname[:30]:30} budget/day {bud_s}")


if __name__ == "__main__":
    main()
