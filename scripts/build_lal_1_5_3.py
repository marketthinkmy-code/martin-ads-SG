"""Build the 1-5-3 lookalike band test: 1 campaign, 5 LAL bands, the same 3 ads in each — PAUSED.

Mirrors the STOCKBLOOM "PURCHASE LAL 1-5%" shape the operator showed: one campaign holding five
ad sets, one per lookalike band, each carrying an identical set of ads so the ONLY thing that
differs between ad sets is which slice of the lookalike they reach.

BANDS
-----
Five audiences derived from the SG paid seed, each a distinct slice rather than five nested
supersets. Meta's range lookalike excludes everything tighter than starting_ratio, so 1-2% does
not contain the top 1%, 2-3% does not contain 1-2%, and so on. That matters here: nested
audiences inside one campaign would bid against each other for the same people and the test
could not attribute a result to a band. Mutually exclusive bands can all run at once.

    1%  ·  1-2%  ·  2-3%  ·  3-4%  ·  4-5%

WHY ABO AND NOT CBO
-------------------
Budget sits on each AD SET, not on the campaign, which is the opposite of this account's usual
pattern and is deliberate. Under CBO, Meta pushes spend to whichever band looks cheapest in the
first hours and the other four receive almost nothing — which is fine when you want the best
result but useless when the question IS "which band works". ABO guarantees every band gets its
own money and therefore its own answer. Convert this to CBO only after a winner is known.

THE THREE ADS
-------------
Chosen on 60-day conversions rather than lifetime, replacing the earlier 1-1-3 build:
    Video 13 三年前他長了10公分        44 regs · CPL 45   (best CPL in the account)
    MAR Video 1 我不会买牛奶            43 regs · CPL 62-72 (across its two live copies)
    Video 孩子15岁以上还有机会长高吗？   14 regs · CPL 66
Each is reused by creative_id, so every ad points at the same page post as the original and
engagement pools onto one post instead of splitting fifteen ways.

Where a creative had several live copies, the copy with the better CPL supplied the id — for
15岁以上 that is 1769022650919449 (CPL 66) rather than 1312364757098700 (CPL 102).

TARGETING
---------
advantage_audience is 0 on every ad set. Left at 1, Meta treats the band as a hint and expands
past it, which would blur the bands into each other and destroy the comparison the campaign
exists to make. Exclusions carry the config list plus the seed itself, so a prospecting test is
not paying to reach people who already bought.

Everything is created PAUSED. Idempotent: band audience ids and entity ids persist in
state/entities_lal_1_5_3.json, so a re-dispatch reuses instead of duplicating.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_lal_1_5_3.json"
PREFIX = "[SG] 儿童长高方程式"
CAMPAIGN_LABEL = "PURCHASE LAL 1-5% | 1-5-3"
SEED_ID = "120257737609370093"          # Cust Paid List (SG) — 448 Singapore buyers
TARGET_COUNTRY = "SG"
DAILY_MYR_PER_ADSET = 30                # ABO: 5 x RM30 = RM150/day total

# (label, starting_ratio, ratio). starting_ratio None = the top slice, 0%-1%.
BANDS: List[Tuple[str, Optional[float], float]] = [
    ("1%",   None, 0.01),
    ("1-2%", 0.01, 0.02),
    ("2-3%", 0.02, 0.03),
    ("3-4%", 0.03, 0.04),
    ("4-5%", 0.04, 0.05),
]

ADS: List[Dict[str, str]] = [
    {"key": "v13",     "creative_id": "1384215930283487",
     "name": "Video 13：三年前他長了10公分"},
    {"key": "nomilk",  "creative_id": "2497538107356049",
     "name": "MAR Video 1：我不会买牛奶"},
    {"key": "v15plus", "creative_id": "1769022650919449",
     "name": "Video：孩子15岁以上还有机会长高吗？"},
]


def load_state() -> Dict[str, Any]:
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def save_state(st: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    excl = list(m.targeting.excluded_custom_audiences or [])
    if SEED_ID not in excl:
        excl.append(SEED_ID)

    st = load_state()
    bands: Dict[str, str] = st.get("bands", {})

    # 1) one lookalike per band ──────────────────────────────────────────────────────
    log.info("═" * 88)
    for label, start, ratio in BANDS:
        if bands.get(label):
            log.info("   · band %-5s already exists (%s)", label, bands[label])
            continue
        spec: Dict[str, Any] = {"ratio": ratio, "country": TARGET_COUNTRY}
        if start is not None:
            spec["starting_ratio"] = start
        name = f"Lookalike ({TARGET_COUNTRY}, {label}) - Cust Paid List (SG)"
        aud = g._request("POST", f"{acct}/customaudiences", data={
            "name": name, "subtype": "LOOKALIKE", "origin_audience_id": SEED_ID,
            "lookalike_spec": json.dumps(spec)})["id"]
        bands[label] = aud
        st["bands"] = bands
        save_state(st)
        log.info("   + band %-5s → %s  %s", label, aud, name)

    # 2) campaign — ABO, so no campaign-level budget ─────────────────────────────────
    campaign_id = st.get("campaign_id")
    if campaign_id:
        log.info("reusing campaign %s", campaign_id)
    else:
        campaign_id = g.create_campaign(acct, **{
            "name": f"{PREFIX} | {CAMPAIGN_LABEL}",
            "objective": m.objective, "buying_type": "AUCTION", "status": "PAUSED",
            "special_ad_categories": m.special_ad_categories,
            # Meta rejects an ABO campaign that does not state this: "You must specify True or
            # False in the field is_adset_budget_sharing_enabled if you are not using campaign
            # budget." False on purpose — sharing lets ad sets lend each other 20% of their
            # budget, which erodes the per-band guarantee that is the whole reason for ABO here.
            "is_adset_budget_sharing_enabled": False,
            # Singapore requires this on the campaign AND on every ad set carrying SG geo, or
            # Meta refuses with "Regional regulated categories value required". build_1_1_10 sets
            # it in both places; a hand-rolled builder has to do the same.
            **({"regional_regulated_categories": m.regional_regulated_categories}
               if m.regional_regulated_categories else {}),
        })["id"]
        st["campaign_id"] = campaign_id
        save_state(st)
        log.info("+ campaign %s (ABO — budget lives on each ad set)", campaign_id)

    # 3) one ad set per band, each with its own budget + 3 ads ───────────────────────
    adsets: Dict[str, str] = st.get("adsets", {})
    built: Dict[str, List[str]] = st.get("built_ads", {})
    total_ads = 0
    for label, _, _ in BANDS:
        adset_id = adsets.get(label)
        if adset_id:
            log.info("── band %-5s reusing ad set %s", label, adset_id)
        else:
            targeting: Dict[str, Any] = {
                "geo_locations": {"countries": m.targeting.countries or ["SG"]},
                "age_min": 25, "age_max": 65,
                "custom_audiences": [{"id": bands[label]}],
                "excluded_custom_audiences": [{"id": i} for i in excl],
                "locales": m.targeting.locales or [1004],
                # 0, not 1 — expansion would blur the bands into each other.
                "targeting_automation": {"advantage_audience": 0},
            }
            adset_id = g.create_adset(acct, **{
                "name": f"AdSet (Purchase LAL {label} | SG 25+)",
                "campaign_id": campaign_id,
                "optimization_goal": m.optimization_goal, "billing_event": "IMPRESSIONS",
                "promoted_object": m.promoted_object, "targeting": targeting,
                "status": "PAUSED",
                "daily_budget": int(DAILY_MYR_PER_ADSET * 100),
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                # SG regulated-category declaration — Meta rejects an SG-geo ad set without it.
                **({"regional_regulated_categories": m.regional_regulated_categories}
                   if m.regional_regulated_categories else {}),
                # SG ad transparency: the verified advertiser + payer must be declared as identity
                # ids or Meta blocks delivery with "Advertiser is missing". Free-text
                # dsa_beneficiary/payor names are not accepted for Singapore.
                **({"regional_regulation_identities": m.regional_regulation_identities}
                   if m.regional_regulation_identities else {}),
            })["id"]
            adsets[label] = adset_id
            st["adsets"] = adsets
            save_state(st)
            log.info("── band %-5s + ad set %s  (RM%d/day, audience %s)",
                     label, adset_id, DAILY_MYR_PER_ADSET, bands[label])

        done = set(built.get(label, []))
        for a in ADS:
            if a["key"] in done:
                log.info("      skip %s (already built)", a["name"][:34])
                continue
            ad = g.create_ad(acct, name=a["name"], adset_id=adset_id,
                             creative={"creative_id": a["creative_id"]},
                             status="PAUSED", conversion_domain=conv)
            done.add(a["key"])
            built[label] = sorted(done)
            st["built_ads"] = built
            save_state(st)
            total_ads += 1
            log.info("      + ad %s ⟵ %s", ad["id"], a["name"][:38])

    log.info("═" * 88)
    log.info("campaign=%s · %d band(s) · %d new ad(s)", campaign_id, len(BANDS), total_ads)
    for label, _, _ in BANDS:
        log.info("   %-5s audience=%s adset=%s", label, bands.get(label), adsets.get(label))
    final_summary(
        log, f"1-5-3 built PAUSED: 1 campaign + {len(BANDS)} lookalike bands (1%, 1-2%, 2-3%, "
             f"3-4%, 4-5% of the 448-person SG paid seed) x {len(ADS)} ads = {len(BANDS)*len(ADS)} "
             f"ads. ABO at RM{DAILY_MYR_PER_ADSET}/day per band (RM{DAILY_MYR_PER_ADSET*len(BANDS)}"
             f"/day total) so every band gets its own budget — under CBO Meta would starve four of "
             f"them and the comparison would not exist. Bands are mutually exclusive slices, so "
             f"they do not bid against each other. Advantage+ audience is OFF everywhere. New "
             f"bands need a few hours to size before anything can deliver.")


if __name__ == "__main__":
    main()
