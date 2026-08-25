"""The 1-3-3 grid: 1 CBO campaign × 3 audiences × the same 3 hooks = 9 cells. PAUSED.

Campaign: [SG] 儿童长高方程式 | Grid 3×3 Hook Test | 1-3-3   ·   CBO RM150/day

THE GRID
--------
Audience axis — three different MECHANISMS, not three similar interest bundles:
    A  Parents 3–17 + Engaged   (the account's proving ground, cloned by id)
    B  LAL 1-2%                 (paid-buyer lookalike, CPL ~65 this week)
    C  Broad SG 25-65           (no detailed targeting — the cheap-delivery wildcard)

Hook axis — the SAME three ads in every ad set, or audience and hook confound each other:
    Video 5 倒數計時             (new countdown angle, script-native copy)
    Hook Edit 04 不买牛奶给孩子喝  (the anchor: best lead→paid in the account, RM302/sale)
    Hook 2 你還在把麵包當早餐？    (best CTR ever measured here, 5.38%, never fairly funded)

Under CBO, Meta concentrates budget into the cheapest cells — the operator knows and wants
this (cheap SG leads first, a winner surfaced second, a full 9-cell map explicitly NOT the
goal). Starved cells are "CBO didn't like it", not "proven bad".

OPERATOR'S EXPLICIT CALLS
-------------------------
· V5 runs BOTH here and in its solo campaign ("给他两处跑") — the solo stays untouched.
· Everything is created PAUSED for preview.

GUARDS (each one earned the hard way in this account)
-----------------------------------------------------
· advantage_audience is sent 0 and VERIFIED after creation on A and B — Meta stored 1 on the
  LAL bands despite being sent 0. If B is not locked, all three audiences become broad and
  the audience axis is dead. C is broad by design, nothing to protect.
· Creative ids resolve from the state files their builds persisted, and each is checked to
  still exist before anything is created — half a grid is worse than none.
· Ad names are the exact historical names (sales attribution stays keyed to the same
  creatives; the grid's own sales are separable via the campaign UTM), and each name is
  checked against the close-target cores of the enforcement scripts so no future sweep can
  catch a grid ad by substring.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_grid_3x3.json"
PREFIX = "[SG] 儿童长高方程式"
CAMPAIGN_LABEL = "Grid 3×3 Hook Test | 1-3-3"
DAILY_MINOR = 15000                                 # RM150/day, CBO
SEED_ID = "120257737609370093"                      # Cust Paid List (SG)
CLONE_ADSET_ID = "120256891851660093"               # Parents 3–17 + Engaged
LAL_1_2_AUDIENCE = "120257761396000093"             # Lookalike (SG, 1-2%) - Cust Paid List (SG)

V5_STATE = Path("state") / "entities_v5_countdown.json"
HOOKEDITS_STATE = Path("state") / "entities_hookedits_shared.json"
BREADHOOKS_STATE = Path("state") / "entities_bread_hooks_shared.json"

# ad-name cores the enforcement/close scripts sweep by key containment — no grid name may
# contain any of these, or a future enforcement run could catch a grid ad.
CLOSE_CORES = ["Video 13：三年前他長了10公分", "MAR Video 1：我不会买牛奶",
               "MAR Video 8（1）：新马版主打牛奶迷思"]

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text()) if p.exists() else {}


def resolve_hooks() -> List[Dict[str, str]]:
    v5 = load_json(V5_STATE)
    he = (load_json(HOOKEDITS_STATE).get("creatives") or {}).get("he04_nomilk") or {}
    bh = (load_json(BREADHOOKS_STATE).get("creatives") or {}).get("bh2") or {}
    hooks = [
        {"key": "v5", "name": "Video 5：倒數計時", "creative": str(v5.get("creative_id") or "")},
        {"key": "he04", "name": "Hook Edit 04：不买牛奶给孩子喝",
         "creative": str(he.get("creative_id") or "")},
        {"key": "bh2", "name": "Hook 2：你還在把麵包當早餐？",
         "creative": str(bh.get("creative_id") or "")},
    ]
    missing = [h["key"] for h in hooks if not h["creative"]]
    if missing:
        raise SystemExit(f"!! creative id(s) missing from state for {missing} — nothing built.")
    for h in hooks:
        nk = cpa.ad_key(h["name"])
        for core in CLOSE_CORES:
            if cpa.ad_key(core) in nk:
                raise SystemExit(f"!! name collision: {h['name']!r} contains close core "
                                 f"{core!r} — refusing to build a sweepable ad.")
    return hooks


def base_spec(m) -> Dict[str, Any]:
    excl = list(m.targeting.excluded_custom_audiences or [])
    if SEED_ID not in excl:
        excl.append(SEED_ID)
    return {
        "geo_locations": {"countries": m.targeting.countries or ["SG"]},
        "age_min": 25, "age_max": 65,
        "excluded_custom_audiences": [{"id": i} for i in excl],
        "locales": m.targeting.locales or [1004],
        "targeting_automation": {"advantage_audience": 0},
    }


def parents_spec(g, s) -> Dict[str, Any]:
    t = g._request("GET", CLONE_ADSET_ID, params={"fields": "targeting"}).get("targeting") or {}
    spec = base_spec(s.meta)
    if t.get("genders"):
        spec["genders"] = t["genders"]
    fs = t.get("flexible_spec")
    if fs:
        spec["flexible_spec"] = fs
    else:
        legacy = {k: t[k] for k in DETAIL_KEYS if t.get(k)}
        if legacy:
            spec["flexible_spec"] = [legacy]
    return spec


def verify_lock(g, adset_id: str, spec: Dict[str, Any], log) -> str:
    """Meta stored advantage_audience=1 on the LAL bands despite being sent 0 — re-read, and
    rewrite our own spec with both switches forced off if the stored value drifted."""
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv = int((t.get("targeting_automation") or {}).get("advantage_audience") or 0)
    rel = (t.get("targeting_relaxation_types") or {})
    drifted = adv != 0 or int(rel.get("custom_audience") or 0) != 0
    if not drifted:
        return "off"
    fix = dict(spec)
    fix["targeting_automation"] = {"advantage_audience": 0}
    fix["targeting_relaxation_types"] = {"custom_audience": 0, "lookalike": 0}
    g._request("POST", adset_id, data={"targeting": json.dumps(fix)})
    t2 = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv2 = int((t2.get("targeting_automation") or {}).get("advantage_audience") or 0)
    log.info("   expansion drifted (adv=%s) → rewrote → adv=%s", adv, adv2)
    return "off" if adv2 == 0 else "STILL ON — fix by hand before activating"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    hooks = resolve_hooks()
    for h in hooks:                       # a dead creative must fail before anything is created
        c = g._request("GET", h["creative"], params={"fields": "id,status"})
        log.info("creative %-18s %s (%s)", h["creative"], h["key"], c.get("status", "?"))

    st = load_json(STATE_PATH)

    # ── campaign (CBO: budget + bid strategy live here) ─────────────────────────
    campaign_id = st.get("campaign_id")
    if campaign_id:
        log.info("reusing campaign %s", campaign_id)
    else:
        campaign_id = g.create_campaign(acct, **{
            "name": f"{PREFIX} | {CAMPAIGN_LABEL}",
            "objective": m.objective, "buying_type": "AUCTION", "status": "PAUSED",
            "special_ad_categories": m.special_ad_categories,
            "daily_budget": DAILY_MINOR,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            **({"regional_regulated_categories": m.regional_regulated_categories}
               if m.regional_regulated_categories else {}),
        })["id"]
        st["campaign_id"] = campaign_id
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("+ campaign %s (CBO RM%d/day)", campaign_id, DAILY_MINOR // 100)

    # ── the three audience cells ────────────────────────────────────────────────
    spec_a = parents_spec(g, s)
    spec_b = base_spec(m)
    spec_b["custom_audiences"] = [{"id": LAL_1_2_AUDIENCE}]
    spec_c = base_spec(m)                 # broad: base spec IS the whole spec
    cells = [
        {"key": "A", "name": "Grid A · Parents 3–17 + Engaged", "spec": spec_a, "lock": True},
        {"key": "B", "name": "Grid B · LAL 1-2%", "spec": spec_b, "lock": True},
        {"key": "C", "name": "Grid C · Broad SG 25+", "spec": spec_c, "lock": False},
    ]

    adsets: Dict[str, str] = st.get("adsets", {})
    built: Dict[str, List[str]] = st.get("built_ads", {})
    locks: List[str] = []
    for cell in cells:
        adset_id = adsets.get(cell["key"])
        if adset_id:
            log.info("── %s reusing ad set %s", cell["key"], adset_id)
        else:
            adset_id = g.create_adset(acct, **{
                "name": cell["name"], "campaign_id": campaign_id,
                "optimization_goal": m.optimization_goal, "billing_event": "IMPRESSIONS",
                "promoted_object": m.promoted_object, "targeting": cell["spec"],
                "status": "PAUSED",
                **({"regional_regulated_categories": m.regional_regulated_categories}
                   if m.regional_regulated_categories else {}),
                **({"regional_regulation_identities": m.regional_regulation_identities}
                   if m.regional_regulation_identities else {}),
            })["id"]
            adsets[cell["key"]] = adset_id
            st["adsets"] = adsets
            STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("── %s + ad set %s  %s", cell["key"], adset_id, cell["name"])
        if cell["lock"]:
            state = verify_lock(g, adset_id, cell["spec"], log)
            locks.append(f"{cell['key']}:{state}")
            log.info("   expansion %s", state)

        done = set(built.get(cell["key"], []))
        for h in hooks:
            if h["key"] in done:
                log.info("      skip %s (already built)", h["name"][:30])
                continue
            ad = g.create_ad(acct, name=h["name"], adset_id=adset_id,
                             creative={"creative_id": h["creative"]},
                             status="PAUSED", conversion_domain=conv)
            done.add(h["key"])
            built[cell["key"]] = sorted(done)
            st["built_ads"] = built
            STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("      + ad %s ⟵ %s", ad["id"], h["name"][:34])

    log.info("═" * 88)
    log.info("campaign=%s · 3 ad sets · 9 ads", campaign_id)
    for cell in cells:
        log.info("   %s %s → %s", cell["key"], cell["name"], adsets.get(cell["key"]))
    final_summary(
        log, f"Grid 3×3 built PAUSED: 1 CBO campaign at RM{DAILY_MINOR // 100}/day × 3 audiences "
             f"(Parents 3–17+Engaged · LAL 1-2% · Broad) × the same 3 hooks (V5 倒數計時 · "
             f"Hook Edit 04 · Bread Hook 2) = 9 cells. Expansion locks: {', '.join(locks)}. "
             f"Per the operator's call, V5's solo campaign keeps running alongside. CBO will "
             f"concentrate on the cheapest cells — that is the point; starved cells are 'CBO "
             f"didn't like it', not 'proven bad'. First read at RM450 spend; the standing kill "
             f"rule applies: a cell that wins CPL but produces zero sheet sales in 14 days is "
             f"Video 13 again and gets cut.")


if __name__ == "__main__":
    main()
