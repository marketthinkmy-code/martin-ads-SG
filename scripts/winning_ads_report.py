"""Top winning SG ads + ad sets from the latest Paid Student List (read-only).

Ranks by REAL paid sales (the sheet), attributed via each sale's UTM (campaign / ad set / ad).
The sheet is SHARED with MY and SG reuses MY creative *names*, so a by-name count mixes both
markets. To isolate SG we match each sale's UTM campaign/ad-set against the SG ad account's own
campaign/ad-set names (those carry the SG prefix, so they never collide with MY). Then:
  · TOP 5 ADS      — by SG-attributed paid sales (life + 60d + 30d), joined to SG spend → CPA
  · TOP 3 AD SETS  — by SG-attributed paid sales, joined to ad-set spend → CPA
Plus a cross-check: whole-sheet by-creative-NAME ranking (MY+SG combined), clearly labelled.
Writes nothing to Meta.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.settings import load_settings

ad_key = cpa.ad_key


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
    acct = s.meta.account_path
    price = s.cpa.price_myr
    tgt, healthy, accpt = s.cpa.target_myr, s.cpa.healthy_max_myr, s.cpa.max_acceptable_myr
    until = today.isoformat()
    d60 = (today - dt.timedelta(days=60)).isoformat()
    cut30, cut60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)

    def windows_of(group):
        life = len(group)
        n60 = sum(1 for x in group if x.date and x.date > cut60)
        n30 = sum(1 for x in group if x.date and x.date > cut30)
        return life, n60, n30

    # ── read + parse the Paid Student List ──────────────────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, cols, header = cpa.parse_sales(values, price)

    n = len(sales) or 1
    pop_camp = sum(1 for x in sales if x.campaign)
    pop_adset = sum(1 for x in sales if x.adset)
    pop_ad = sum(1 for x in sales if x.ad)
    ds = sorted(x.date for x in sales if x.date)

    print(f"WINNING ADS/ADSETS — SG · Paid Student List '{s.cpa.sales_tab}' · today MYT={today}")
    print(f"CPA target RM{tgt:.0f} / healthy RM{healthy:.0f} / acceptable RM{accpt:.0f}\n")
    print(f"sheet rows parsed as sales: {len(sales)}   ·   header cols: {cols}")
    print(f"UTM populated → campaign {100*pop_camp//n}% · ad-set {100*pop_adset//n}% · ad {100*pop_ad//n}%")
    if ds:
        print(f"sale dates: {ds[0]} … {ds[-1]}   (undated rows: {sum(1 for x in sales if not x.date)})")
    print()

    # ── SG account entities (names + spend) ─────────────────────────────────────
    g = graph_client(s)
    camps = g._get_all(f"{acct}/campaigns", {"fields": "id,name,effective_status,daily_budget", "limit": 300})
    camp_by_id = {c["id"]: c for c in camps}
    adsets = g._get_all(f"{acct}/adsets", {"fields": "id,name,campaign_id,effective_status", "limit": 500})
    ads = g._get_all(f"{acct}/ads", {"fields": "id,name,adset_id,campaign_id,effective_status", "limit": 500})

    def spend_map(level, idkey, *, preset=None, tr=None):
        rows = g.account_insights(acct, level=level, fields=f"{idkey},spend", date_preset=preset, time_range=tr)
        return {r.get(idkey): _f(r.get("spend")) for r in rows}

    ad_sp60 = spend_map("ad", "ad_id", tr={"since": d60, "until": until})
    ad_splife = spend_map("ad", "ad_id", preset="maximum")
    adset_sp60 = spend_map("adset", "adset_id", tr={"since": d60, "until": until})
    adset_splife = spend_map("adset", "adset_id", preset="maximum")

    sg_camp_keys = {ad_key(c.get("name")) for c in camps}
    sg_adset_keys = {ad_key(a.get("name")) for a in adsets}

    sg_ad_ids_by_key = defaultdict(list)
    sg_ad_name_by_key = {}
    sg_ad_status_by_key = defaultdict(set)
    for ad in ads:
        k = ad_key(ad.get("name"))
        sg_ad_ids_by_key[k].append(ad["id"])
        sg_ad_name_by_key.setdefault(k, ad.get("name"))
        sg_ad_status_by_key[k].add(ad.get("effective_status"))

    sg_adset_ids_by_tuple = defaultdict(list)
    sg_adset_disp = {}
    for a in adsets:
        cname = camp_by_id.get(a.get("campaign_id"), {}).get("name", "")
        tk = (ad_key(cname), ad_key(a.get("name")))
        sg_adset_ids_by_tuple[tk].append(a["id"])
        sg_adset_disp.setdefault(tk, (a.get("name"), cname))

    # ── isolate SG sales (UTM campaign or ad-set matches an SG entity) ──────────
    sg_sales = [x for x in sales
                if ad_key(x.campaign) in sg_camp_keys or ad_key(x.adset) in sg_adset_keys]
    fallback = ""
    if not sg_sales:
        sg_sales = [x for x in sales if ad_key(x.ad) in sg_ad_ids_by_key]
        fallback = ("  ⚠️ no sale matched an SG campaign/ad-set UTM — fell back to matching by AD "
                    "NAME (shared with MY, so these counts may include MY sales).")
    print(f"SG-attributed sales: {len(sg_sales)} of {len(sales)}{fallback}\n")

    # ── TOP 5 SG ADS (by paid sales) ────────────────────────────────────────────
    by_ad = defaultdict(list)
    for x in sg_sales:
        k = ad_key(x.ad)
        if k:
            by_ad[k].append(x)
    ad_rows = []
    for k, grp in by_ad.items():
        life, n60, n30 = windows_of(grp)
        ids = sg_ad_ids_by_key.get(k, [])
        sp60 = sum(ad_sp60.get(i, 0.0) for i in ids)
        splife = sum(ad_splife.get(i, 0.0) for i in ids)
        st = sg_ad_status_by_key.get(k, set())
        live = "ACTIVE" if "ACTIVE" in st else ("PAUSED" if st else "not-in-SG")
        ad_rows.append({
            "name": sg_ad_name_by_key.get(k) or grp[0].ad, "n_ids": len(ids), "live": live,
            "life": life, "n60": n60, "n30": n30, "sp60": sp60, "splife": splife,
            "cpa60": cpa.cpa(sp60, n60), "cpalife": cpa.cpa(splife, life),
        })
    top_ads = sorted(ad_rows, key=lambda r: (-r["life"], -r["n60"], (r["cpa60"] or math.inf)))

    print("═" * 92)
    print("TOP 5 SG ADS  — ranked by real paid sales (life), CPA = SG spend ÷ sales")
    print("═" * 92)
    if not top_ads:
        print("  (no SG-attributed ad sales found)")
    for i, r in enumerate(top_ads[:5], 1):
        print(f"{i}. {r['name'][:58]}   [{r['live']}]")
        print(f"     sales: life {r['life']} · 60d {r['n60']} · 30d {r['n30']}    "
              f"SG spend 60d RM{r['sp60']:.0f} → CPA {_s(r['cpa60'])}   ·   life CPA {_s(r['cpalife'])}")

    # ── TOP 3 SG AD SETS (by paid sales) ────────────────────────────────────────
    by_adset = defaultdict(list)
    for x in sg_sales:
        by_adset[(ad_key(x.campaign), ad_key(x.adset))].append(x)
    adset_rows = []
    for tk, grp in by_adset.items():
        life, n60, n30 = windows_of(grp)
        ids = sg_adset_ids_by_tuple.get(tk, [])
        sp60 = sum(adset_sp60.get(i, 0.0) for i in ids)
        splife = sum(adset_splife.get(i, 0.0) for i in ids)
        disp = sg_adset_disp.get(tk)
        name = disp[0] if disp else (grp[0].adset or "∅")
        camp = disp[1] if disp else (grp[0].campaign or "∅")
        adset_rows.append({
            "adset": name, "camp": camp, "life": life, "n60": n60, "n30": n30,
            "sp60": sp60, "splife": splife, "cpa60": cpa.cpa(sp60, n60), "cpalife": cpa.cpa(splife, life),
        })
    top_adsets = sorted(adset_rows, key=lambda r: (-r["life"], -r["n60"], (r["cpa60"] or math.inf)))

    print("\n" + "═" * 92)
    print("TOP 3 SG AD SETS  — ranked by real paid sales (life)")
    print("═" * 92)
    if not top_adsets:
        print("  (no SG-attributed ad-set sales found)")
    for i, r in enumerate(top_adsets[:3], 1):
        print(f"{i}. {r['adset'][:52]}   ·   {r['camp'][:46]}")
        print(f"     sales: life {r['life']} · 60d {r['n60']} · 30d {r['n30']}    "
              f"ad-set spend 60d RM{r['sp60']:.0f} → CPA {_s(r['cpa60'])}   ·   life CPA {_s(r['cpalife'])}")

    # ── CROSS-CHECK: whole-sheet by creative NAME (MY+SG combined) ──────────────
    by_name_all = defaultdict(list)
    for x in sales:
        k = ad_key(x.ad)
        if k:
            by_name_all[k].append(x)
    name_rows = []
    for k, grp in by_name_all.items():
        life, n60, n30 = windows_of(grp)
        in_sg = "SG✓" if k in sg_ad_ids_by_key else "—"
        name_rows.append({"name": sg_ad_name_by_key.get(k) or grp[0].ad,
                          "life": life, "n60": n60, "n30": n30, "in_sg": in_sg})
    name_rows.sort(key=lambda r: (-r["life"], -r["n60"]))

    print("\n" + "═" * 92)
    print("CROSS-CHECK — whole-sheet by creative NAME (MY+SG COMBINED — names are shared)")
    print("═" * 92)
    for i, r in enumerate(name_rows[:10], 1):
        print(f"{i:2}. {r['name'][:56]:56} life {r['life']:>3} · 60d {r['n60']:>2} · 30d {r['n30']:>2}  [{r['in_sg']}]")


if __name__ == "__main__":
    main()
