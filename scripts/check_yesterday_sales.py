"""Yesterday's paid sales (SG sheet) → ad name / ad set, cross-referenced against
the LIVE monitor verdict for every active ad — so we can confirm each winning ad
is (a) still ACTIVE and (b) NOT about to be wrongly auto-paused.

Robust date/campaign column detection: cpa.find_columns misses the Chinese
報名日期 header + the SG tab's campaign column, so we scan/sniff for them here.
Also prints the monitor's FULL current kill-list (every active ad it WOULD pause),
so no at-risk winner is missed. Read-only.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.monitor_cpl import evaluate_account
from adbot.settings import load_settings

DATE_HDRS = ("报名日期", "報名日期", "date", "日期", "报名", "報名", "成交日期", "付款日期", "购买日期")
CAMP_HDRS = ("utm campaign", "campaign name", "campaign", "广告系列", "廣告系列", "活动", "活動")


def _hkey(s: str) -> str:
    return (s or "").strip().lower()


def _find_col(header, needles) -> int:
    keys = [_hkey(h) for h in header]
    for n in needles:
        for i, k in enumerate(keys):
            if n in k:
                return i
    return -1


def _sniff_date_col(rows, hdr_idx, ncols) -> int:
    best, best_hits = -1, 0
    for c in range(ncols):
        hits = 0
        for row in rows[hdr_idx + 1: hdr_idx + 81]:
            if c < len(row) and cpa.parse_date(row[c]):
                hits += 1
        if hits > best_hits:
            best, best_hits = c, hits
    return best if best_hits >= 10 else -1


def _cpl(d) -> str:
    return "n/a" if d.cpl is None else ("∞" if d.cpl == math.inf else f"{d.cpl:.0f}")


def _cpa(d) -> str:
    if d.cpa is None:
        return ""
    v = "∞" if d.cpa == math.inf else f"{d.cpa:.0f}"
    return f" · CPA={v}(60d {d.cpa_sales} sale, age {d.age_days}d)"


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    yday = today - dt.timedelta(days=1)

    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)

    # header row = first with a UTM ad column
    hdr_idx, cols = 0, cpa.find_columns(values[0] if values else [])
    for i, row in enumerate(values[:8]):
        c = cpa.find_columns(row)
        if c.get("ad", -1) >= 0 and c.get("adset", -1) >= 0:
            hdr_idx, cols = i, c
            break
    header = values[hdr_idx]
    ncols = max(len(r) for r in values[hdr_idx:hdr_idx + 60])

    ad_col, adset_col, amt_col = cols.get("ad", 15), cols.get("adset", 14), cols.get("amount", 7)
    date_col = cols.get("date", -1)
    if date_col < 0:
        date_col = _find_col(header, DATE_HDRS)
    if date_col < 0:
        date_col = _sniff_date_col(values, hdr_idx, ncols)
    camp_col = cols.get("campaign", -1)
    if camp_col < 0:
        camp_col = _find_col(header, CAMP_HDRS)

    print(f"Sheet tab : {s.cpa.sales_tab!r}  ·  header row #{hdr_idx}")
    print(f"header    : {[h[:16] for h in header[:20]]}")
    print(f"resolved cols → date={date_col} adset={adset_col} ad={ad_col} campaign={camp_col} amount={amt_col}")
    if date_col >= 0:
        print(f"date col header={header[date_col]!r}  sample={[r[date_col] for r in values[hdr_idx+1:hdr_idx+4] if date_col < len(r)]}")
    print(f"Today (MYT)={today} · Yesterday={yday}\n")

    def cell(row, i):
        return row[i] if 0 <= i < len(row) else ""

    y = []
    for row in values[hdr_idx + 1:]:
        d = cpa.parse_date(cell(row, date_col)) if date_col >= 0 else None
        if d != yday:
            continue
        y.append((cpa.norm(cell(row, ad_col)), cpa.norm(cell(row, adset_col)),
                  cpa.norm(cell(row, camp_col)) if camp_col >= 0 else "",
                  cpa._money(cell(row, amt_col), s.cpa.price_myr)))

    print(f"Sales dated yesterday: {len(y)}")
    for ad, adset, camp, amt in y:
        print(f"  · ad={ad[:38]!r:40} adset={adset[:24]!r:26} camp={camp[:20]!r:22} RM{amt:.0f}")

    per_ad = defaultdict(int)
    ad_adset = defaultdict(set)
    for ad, adset, camp, amt in y:
        if ad:
            per_ad[ad] += 1
            ad_adset[ad].add(adset)
    print(f"\nDistinct winning ad names yesterday: {len(per_ad)}")

    g = graph_client(s)
    decisions = evaluate_account(g, s)
    by_name = defaultdict(list)
    for d in decisions:
        by_name[cpa.norm(d.name)].append(d)
    would_pause = [d for d in decisions if d.should_pause]
    print(f"Monitor evaluated {len(decisions)} active reg-optimized ads · "
          f"would pause {len(would_pause)} right now.\n")

    print("═" * 92)
    print(" STATUS of each yesterday-winning ad (as the cron sees it RIGHT NOW)")
    print("═" * 92)
    at_risk, not_running, safe = [], [], []
    for ad in sorted(per_ad, key=lambda a: -per_ad[a]):
        n = per_ad[ad]
        ds = by_name.get(ad, [])
        if not ds:
            not_running.append(ad)
            print(f"  ❌ NOT RUNNING ({n} sale)  ad={ad[:46]!r} — no ACTIVE reg-optimized ad by this name")
            continue
        for d in ds:
            if d.should_pause:
                at_risk.append((ad, d)); tag = "⚠️  WOULD PAUSE"
            else:
                safe.append((ad, d)); tag = "✅ SAFE"
            print(f"  {tag} ({n} sale)  ad={ad[:46]!r}")
            print(f"          spend=RM{d.spend:.0f} reg={d.results:.0f} CPL={_cpl(d)}{_cpa(d)} — {d.reason}")

    print("\n" + "═" * 92)
    print(f" SUMMARY: {len(per_ad)} winner(s) yesterday · {len(safe)} SAFE · "
          f"{len(at_risk)} AT RISK · {len(not_running)} NOT running")
    print("═" * 92)
    if at_risk:
        print(" ⚠️  AT-RISK winners (monitor WOULD pause; protect via kpi.cpl_hold):")
        for ad, d in at_risk:
            print(f"      {ad!r}  CPL={_cpl(d)} — {d.reason}")
    if not_running:
        print(" ❌ NOT-RUNNING winners (paused / old creative — reactivate if wanted):")
        for ad in not_running:
            print(f"      {ad!r}")
    if not at_risk and not not_running and per_ad:
        print(" 🎉 All yesterday's winners are ACTIVE and SAFE.")

    print("\n" + "═" * 92)
    print(f" FULL monitor kill-list right now ({len(would_pause)} ad(s) it WOULD pause):")
    print("═" * 92)
    for d in would_pause:
        print(f"  ⚠️ {d.name[:52]!r}  spend=RM{d.spend:.0f} reg={d.results:.0f} CPL={_cpl(d)}{_cpa(d)} — {d.reason}")


if __name__ == "__main__":
    main()
