"""Top winning SG ads + ad sets from the latest Paid Student List — SG-ONLY (read-only).

The Paid Student List is SHARED with MY, and early SG was a 1:1 clone of MY with byte-identical
campaign/ad-set names — so a naive by-name match leaks MY sales into SG (proven: ad sets with
28 sales but RM0 SG spend). This report removes that contamination two ways:

  1. SPEND-GATE  — a sale only counts as SG if its UTM campaign matches an SG-account campaign
                   that has REAL lifetime SG spend > 0. Kills the RM0 name-collision ghosts.
  2. PROVABLY-SG — separately flags sales whose UTM campaign is SG-distinctively named
                   ([SG] / MARTIN-SG), which a MY campaign can never carry. This is the hard
                   floor of "definitely SG".

CPA = real SG account spend ÷ SG-attributed sales (target RM740). Writes nothing to Meta.
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


def is_sg_name(name: str) -> bool:
    """True only for SG-distinctive campaign names ([SG] / MARTIN-SG) — MY never carries these."""
    n = " ".join((name or "").split()).casefold()
    return ("[sg]" in n) or ("martin-sg" in n) or ("martin sg" in n)


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
    ds = sorted(x.date for x in sales if x.date)

    print(f"WINNING ADS/ADSETS — SG-ONLY · '{s.cpa.sales_tab}' · today MYT={today}")
    print(f"CPA target RM{tgt:.0f} / healthy RM{healthy:.0f} / acceptable RM{accpt:.0f}")
    print(f"sheet sales rows: {len(sales)}   ·   dates {ds[0] if ds else '?'} … {ds[-1] if ds else '?'}\n")

    # ── SG account entities + real SG spend ─────────────────────────────────────
    g = graph_client(s)
    camps = g._get_all(f"{acct}/campaigns", {"fields": "id,name,effective_status,daily_budget", "limit": 300})
    adsets = g._get_all(f"{acct}/adsets", {"fields": "id,name,campaign_id,effective_status", "limit": 500})
    ads = g._get_all(f"{acct}/ads", {"fields": "id,name,adset_id,campaign_id,effective_status", "limit": 500})
    camp_by_id = {c["id"]: c for c in camps}

    def spend_map(level, idkey, *, preset=None, tr=None):
        rows = g.account_insights(acct, level=level, fields=f"{idkey},spend", date_preset=preset, time_range=tr)
        return {r.get(idkey): _f(r.get("spend")) for r in rows}

    camp_splife = spend_map("campaign", "campaign_id", preset="maximum")
    ad_sp60 = spend_map("ad", "ad_id", tr={"since": d60, "until": until})
    ad_splife = spend_map("ad", "ad_id", preset="maximum")
    adset_sp60 = spend_map("adset", "adset_id", tr={"since": d60, "until": until})
    adset_splife = spend_map("adset", "adset_id", preset="maximum")

    # campaign name-key → did any SG campaign of that name actually spend? is any distinctive?
    camp_spent_keys, camp_distinct_keys = set(), set()
    for c in camps:
        k = ad_key(c.get("name"))
        if camp_splife.get(c["id"], 0.0) > 0:
            camp_spent_keys.add(k)
        if is_sg_name(c.get("name")):
            camp_distinct_keys.add(k)

    # ad-name / adset maps for joining spend + display names
    sg_ad_ids_by_key = defaultdict(list)
    sg_ad_name_by_key, sg_ad_status_by_key = {}, defaultdict(set)
    for a in ads:
        k = ad_key(a.get("name"))
        sg_ad_ids_by_key[k].append(a["id"])
        sg_ad_name_by_key.setdefault(k, a.get("name"))
        sg_ad_status_by_key[k].add(a.get("effective_status"))
    sg_adset_ids_by_tuple = defaultdict(list)
    sg_adset_disp = {}
    sg_adset_status_by_tuple = defaultdict(set)
    for a in adsets:
        cname = camp_by_id.get(a.get("campaign_id"), {}).get("name", "")
        tk = (ad_key(cname), ad_key(a.get("name")))
        sg_adset_ids_by_tuple[tk].append(a["id"])
        sg_adset_disp.setdefault(tk, (a.get("name"), cname))
        sg_adset_status_by_tuple[tk].add(a.get("effective_status"))

    # ── SG sales = UTM campaign matches an SG campaign that really spent ─────────
    def is_distinct_sale(x):
        return ("[sg]" in x.campaign) or ("martin-sg" in x.campaign) or ("martin sg" in x.campaign)

    sg_sales = [x for x in sales if ad_key(x.campaign) in camp_spent_keys]
    distinct_sales = [x for x in sales if is_distinct_sale(x)]

    print(f"SG sales (campaign had real SG spend):   {len(sg_sales)}")
    print(f"  └ of which PROVABLY SG ([SG]/MARTIN-SG named campaign): {len(distinct_sales)}")
    print(f"  (dropped {len(sales) - len(sg_sales)} rows whose campaign never spent in the SG "
          f"account → those were MY / name-collision)\n")

    # ── TOP 5 SG ADS ────────────────────────────────────────────────────────────
    by_ad = defaultdict(list)
    for x in sg_sales:
        k = ad_key(x.ad)
        if k:
            by_ad[k].append(x)
    ad_rows = []
    for k, grp in by_ad.items():
        life, n60, n30 = windows_of(grp)
        prov = sum(1 for x in grp if is_distinct_sale(x))
        ids = sg_ad_ids_by_key.get(k, [])
        sp60 = sum(ad_sp60.get(i, 0.0) for i in ids)
        splife = sum(ad_splife.get(i, 0.0) for i in ids)
        st = sg_ad_status_by_key.get(k, set())
        live = "ACTIVE" if "ACTIVE" in st else ("PAUSED" if st else "not-in-SG")
        ad_rows.append({"name": sg_ad_name_by_key.get(k) or grp[0].ad, "live": live,
                        "life": life, "n60": n60, "n30": n30, "prov": prov,
                        "sp60": sp60, "splife": splife,
                        "cpa60": cpa.cpa(sp60, n60), "cpalife": cpa.cpa(splife, life)})
    top_ads = sorted(ad_rows, key=lambda r: (-r["life"], -r["n60"], (r["cpa60"] or math.inf)))

    print("═" * 94)
    print("TOP 5 SG ADS  — ranked by SG paid sales (life);  CPA = real SG spend ÷ SG sales")
    print("═" * 94)
    for i, r in enumerate(top_ads[:5], 1):
        tag = "✅provably-SG" if r["prov"] == r["life"] else f"⚠️{r['prov']}/{r['life']} provably-SG"
        print(f"{i}. {r['name'][:56]}   [{r['live']}]  {tag}")
        print(f"     sales life {r['life']} · 60d {r['n60']} · 30d {r['n30']}    "
              f"SG spend 60d RM{r['sp60']:.0f} → CPA {_s(r['cpa60'])}   ·   life CPA {_s(r['cpalife'])}")

    # ── TOP 3 SG AD SETS ────────────────────────────────────────────────────────
    by_adset = defaultdict(list)
    for x in sg_sales:
        by_adset[(ad_key(x.campaign), ad_key(x.adset))].append(x)
    adset_rows = []
    for tk, grp in by_adset.items():
        life, n60, n30 = windows_of(grp)
        prov = sum(1 for x in grp if is_distinct_sale(x))
        ids = sg_adset_ids_by_tuple.get(tk, [])
        sp60 = sum(adset_sp60.get(i, 0.0) for i in ids)
        splife = sum(adset_splife.get(i, 0.0) for i in ids)
        disp = sg_adset_disp.get(tk)
        name = disp[0] if disp else (grp[0].adset or "∅")
        camp = disp[1] if disp else (grp[0].campaign or "∅")
        live = "🟢LIVE" if "ACTIVE" in sg_adset_status_by_tuple.get(tk, set()) else "🔴paused"
        adset_rows.append({"adset": name, "camp": camp, "live": live, "life": life, "n60": n60,
                          "n30": n30, "prov": prov, "sp60": sp60, "splife": splife,
                          "cpa60": cpa.cpa(sp60, n60), "cpalife": cpa.cpa(splife, life)})
    top_adsets = sorted(adset_rows, key=lambda r: (-r["life"], -r["n60"], (r["cpa60"] or math.inf)))

    print("\n" + "═" * 94)
    print("TOP 3 SG AD SETS  — ranked by SG paid sales (life)  ·  🟢LIVE = running now / 🔴paused")
    print("═" * 94)
    for i, r in enumerate(top_adsets[:3], 1):
        tag = "✅provably-SG" if r["prov"] == r["life"] else f"⚠️{r['prov']}/{r['life']} provably-SG"
        print(f"{i}. [{r['live']}] {r['adset'][:44]}  ·  {r['camp'][:38]}   {tag}")
        print(f"     sales life {r['life']} · 60d {r['n60']} · 30d {r['n30']}    "
              f"ad-set spend 60d RM{r['sp60']:.0f} → CPA {_s(r['cpa60'])}   ·   life CPA {_s(r['cpalife'])}")

    # ── PROVABLY-SG only (hard floor, [SG]/MARTIN-SG campaigns) ──────────────────
    print("\n" + "═" * 94)
    print("PROVABLY-SG ONLY — ads under [SG]/MARTIN-SG campaigns (zero MY overlap possible)")
    print("═" * 94)
    by_ad_p = defaultdict(list)
    for x in distinct_sales:
        k = ad_key(x.ad)
        if k:
            by_ad_p[k].append(x)
    prov_rows = []
    for k, grp in by_ad_p.items():
        life, n60, n30 = windows_of(grp)
        ids = sg_ad_ids_by_key.get(k, [])
        sp60 = sum(ad_sp60.get(i, 0.0) for i in ids)
        prov_rows.append({"name": sg_ad_name_by_key.get(k) or grp[0].ad,
                         "life": life, "n60": n60, "n30": n30, "cpa60": cpa.cpa(sp60, n60)})
    if not prov_rows:
        print("  (no sales yet under an SG-distinctively-named campaign)")
    for i, r in enumerate(sorted(prov_rows, key=lambda r: (-r["life"], -r["n60"]))[:8], 1):
        print(f"{i}. {r['name'][:56]:56} life {r['life']:>3} · 60d {r['n60']:>2} · 30d {r['n30']:>2} "
              f"· 60d CPA {_s(r['cpa60'])}")


if __name__ == "__main__":
    main()
