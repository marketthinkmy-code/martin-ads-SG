"""SCALE analysis (read-only): which ACTIVE ads are actually making money, how much
headroom they have, and where to add budget.

For every active registration-optimized ad it assembles, per rolling window:
  - spend + registrations + CPL   (from Meta insights: 7d / 14d / 30d / 60d / lifetime)
  - real PAID sales + CPA          (from the Paid Student List sheet, ad-name keyed)
then classifies each ad into a scale tier and rolls the picture up to the CBO campaign
level (current daily budget vs. what the numbers justify). Writes nothing to Meta.

Scale tiers (against the SG KPI: CPL ceiling 65, CPA target 740 / healthy 860 / acc 1040):
  ⭐ STAR   — proven profit (>=3 life sales, 60d CPA<=target) + still converting cheap  -> scale hard
  🟢 SCALE  — profitable (60d CPA<=healthy, >=2 sales) + recent CPL under ceiling        -> +20% budget
  🟡 DUP    — converts but thin (1-2 sales) or CPA in the 860-1040 band                  -> duplicate-test
  🔵 WATCH  — cheap registrations, no paid sale YET (attribution lag / top funnel)        -> hold, watch CPA
  🔴 HOLD   — over CPL now, or CPA>1040, or stalled                                       -> do not scale
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

WINDOWS = (("7d", "last_7d"), ("14d", "last_14d"), ("30d", "last_30d"))


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _cpl(sp: float, reg: float):
    return (sp / reg) if reg > 0 else (math.inf if sp > 0 else None)


def _s(v) -> str:
    return "—" if v is None else ("∞" if v == math.inf else f"{v:.0f}")


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    want = (s.meta.conversion_event or "").upper()
    ceil = s.kpi.cpl_threshold_myr
    tgt, healthy, acc = s.cpa.target_myr, s.cpa.healthy_max_myr, s.cpa.max_acceptable_myr
    until = today.isoformat()
    d60 = (today - dt.timedelta(days=60)).isoformat()

    # ── sheet sales -> paid sales by ad NAME (60d + lifetime) ───────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    cut60 = today - dt.timedelta(days=60)
    sold60, soldlife = defaultdict(int), defaultdict(int)
    for sale in sales:
        k = cpa.ad_key(sale.ad)
        if not k:
            continue
        soldlife[k] += 1
        if sale.date and sale.date > cut60:
            sold60[k] += 1

    g = graph_client(s)

    # ── campaigns: id -> (name, effective_status, daily CBO budget) ─────────────
    camps = g._get_all(f"{acct}/campaigns",
                       {"fields": "id,name,effective_status,daily_budget,lifetime_budget", "limit": 300})
    camp_by_id = {c["id"]: c for c in camps}

    # ── per-ad insight windows (account-level, cheap): spend + registrations ────
    win_spend, win_reg = {}, {}
    for tag, preset in WINDOWS:
        rows = g.account_insights(acct, level="ad", fields="ad_id,spend,actions", date_preset=preset)
        win_spend[tag] = {r.get("ad_id"): _f(r.get("spend")) for r in rows}
        win_reg[tag] = {r.get("ad_id"): extract_results(r.get("actions"), token) for r in rows}
    sp60 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", time_range={"since": d60, "until": until})}
    splife = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", date_preset="maximum")}

    # ── active reg-optimized ads ────────────────────────────────────────────────
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,created_time,effective_status,campaign_id,adset{name,promoted_object}",
        "limit": 500})

    recs = []
    for ad in ads:
        if ad.get("effective_status") != "ACTIVE":
            continue
        adset = ad.get("adset") or {}
        if ((adset.get("promoted_object") or {}).get("custom_event_type") or "").upper() != want:
            continue
        aid, name = ad["id"], ad.get("name", ad["id"])
        camp = camp_by_id.get(ad.get("campaign_id"), {})
        key = cpa.ad_key(name)
        n60, nlife = sold60.get(key, 0), soldlife.get(key, 0)
        cpa60 = cpa.cpa(sp60.get(aid, 0.0), n60)
        cpalife = cpa.cpa(splife.get(aid, 0.0), nlife)
        cpl14 = _cpl(win_spend["14d"].get(aid, 0.0), win_reg["14d"].get(aid, 0.0))
        created = cpa.parse_date((ad.get("created_time") or "")[:10])
        age = (today - created).days if created else None

        # ---- classify ----
        recent_reg = win_reg["14d"].get(aid, 0.0)
        cpl_ok = cpl14 is not None and cpl14 != math.inf and cpl14 <= ceil
        prof60 = cpa60 is not None and cpa60 != math.inf
        if nlife >= 3 and prof60 and cpa60 <= tgt and recent_reg > 0 and cpl_ok:
            tier, order = "⭐STAR", 0
        elif prof60 and cpa60 <= healthy and n60 + nlife >= 2 and cpl_ok:
            tier, order = "🟢SCALE", 1
        elif nlife >= 1 and (cpa60 is None or cpa60 <= acc):
            tier, order = "🟡DUP", 2
        elif recent_reg > 0 and cpl_ok:
            tier, order = "🔵WATCH", 3
        else:
            tier, order = "🔴HOLD", 4

        recs.append({
            "tier": tier, "order": order, "name": name, "camp": camp.get("name", "∅"),
            "camp_id": ad.get("campaign_id"), "adset": adset.get("name", "∅"),
            "sp7": win_spend["7d"].get(aid, 0.0), "reg7": win_reg["7d"].get(aid, 0.0),
            "sp14": win_spend["14d"].get(aid, 0.0), "reg14": recent_reg, "cpl14": cpl14,
            "sp30": win_spend["30d"].get(aid, 0.0), "reg30": win_reg["30d"].get(aid, 0.0),
            "sp60": sp60.get(aid, 0.0), "n60": n60, "cpa60": cpa60,
            "splife": splife.get(aid, 0.0), "nlife": nlife, "cpalife": cpalife, "age": age,
        })

    # ── AD-LEVEL scale board ────────────────────────────────────────────────────
    print(f"SCALE analysis — SG · today MYT={today}  ·  CPL ceiling RM{ceil:.0f} · "
          f"CPA target {tgt:.0f}/healthy {healthy:.0f}/acc {acc:.0f}\n")
    print(f"Active reg-optimized ads: {len(recs)}")
    for t in ("⭐STAR", "🟢SCALE", "🟡DUP", "🔵WATCH", "🔴HOLD"):
        print(f"   {t}: {sum(1 for r in recs if r['tier'] == t)}", end="")
    print("\n")

    hdr = (f"{'tier':8}|{'ad name':34}|{'7d sp/reg/CPL':>15}|{'14d sp/reg/CPL':>16}|"
           f"{'60d sp/sale/CPA':>18}|{'life sp/sale/CPA':>18}|age")
    print(hdr); print("-" * len(hdr))
    for r in sorted(recs, key=lambda r: (r["order"], -(r["nlife"]), (r["cpa60"] or math.inf))):
        c7 = f"{r['sp7']:.0f}/{r['reg7']:.0f}/{_s(_cpl(r['sp7'], r['reg7']))}"
        c14 = f"{r['sp14']:.0f}/{r['reg14']:.0f}/{_s(r['cpl14'])}"
        c60 = f"{r['sp60']:.0f}/{r['n60']}/{_s(r['cpa60'])}"
        cl = f"{r['splife']:.0f}/{r['nlife']}/{_s(r['cpalife'])}"
        print(f"{r['tier']:8}|{r['name'][:34]:34}|{c7:>15}|{c14:>16}|{c60:>18}|{cl:>18}|{r['age']}")

    # ── CAMPAIGN roll-up (CBO budget lives here) ────────────────────────────────
    print("\n" + "═" * 96)
    print(" CAMPAIGN roll-up — CBO daily budget vs. what the numbers justify")
    print("═" * 96)
    by_camp = defaultdict(lambda: {"sp30": 0.0, "reg30": 0.0, "sp60": 0.0, "n60": 0,
                                   "nlife": 0, "splife": 0.0, "stars": 0, "scale": 0, "ads": 0})
    for r in recs:
        b = by_camp[(r["camp_id"], r["camp"])]
        for k in ("sp30", "reg30", "sp60", "n60", "nlife", "splife"):
            b[k] += r[k]
        b["ads"] += 1
        b["stars"] += r["tier"] == "⭐STAR"
        b["scale"] += r["tier"] == "🟢SCALE"
    for (cid, cname), b in sorted(by_camp.items(), key=lambda kv: -kv[1]["n60"]):
        c = camp_by_id.get(cid, {})
        budget = _f(c.get("daily_budget")) / 100 if c.get("daily_budget") else None
        cpa60 = cpa.cpa(b["sp60"], b["n60"])
        cpl30 = _cpl(b["sp30"], b["reg30"])
        bstr = f"RM{budget:.0f}/day CBO" if budget else "ABO/ad-set budget"
        rec = ""
        if b["stars"] or b["scale"]:
            if cpa60 is not None and cpa60 != math.inf and cpa60 <= healthy:
                rec = f"→ raise budget +20% (to ~RM{budget*1.2:.0f})" if budget else "→ raise winning ad-set budgets +20%"
            elif cpa60 is not None and cpa60 != math.inf and cpa60 <= acc:
                rec = "→ hold budget, duplicate the winners into a fresh campaign"
        print(f"\n▸ {cname[:70]}")
        print(f"    {bstr} · {b['ads']} active ad(s) · ⭐{b['stars']} 🟢{b['scale']}")
        print(f"    30d: RM{b['sp30']:.0f} / {b['reg30']:.0f} reg / CPL {_s(cpl30)}   ·   "
              f"60d: RM{b['sp60']:.0f} / {b['n60']} sale / CPA {_s(cpa60)}   ·   life sales {b['nlife']}")
        if rec:
            print(f"    {rec}")

    tot_sp60 = sum(r["sp60"] for r in recs)
    tot_n60 = sum(r["n60"] for r in recs)
    print(f"\nAccount active-ads blended (60d): RM{tot_sp60:,.0f} / {tot_n60} paid sale "
          f"= CPA RM{_s(cpa.cpa(tot_sp60, tot_n60))}  (target RM{tgt:.0f})")


if __name__ == "__main__":
    main()
