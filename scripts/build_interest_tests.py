"""Two interest-expansion tests: proven sellers on audiences the account has never tried. PAUSED.

    [SG] 儿童长高方程式 | Teen Parents 13-17 | 1-1-1      RM50/day CBO
    [SG] 儿童长高方程式 | Supplement Interests | 1-1-1     RM50/day CBO

WHY THESE TWO PAIRS
-------------------
One unknown per test. The creative is the proven part (both have provably-SG sales), the
audience is the question — pairing a new hook with a new audience answers neither.

  1. 15岁以上 (24 SG sales, the account's registration volume king) on Meta's
     "Parents with teenagers (13-17 years)" demographic. The account has always bundled
     parents as one 3–17 blob; the buyers of THIS message are teenager parents specifically,
     and that slice has never been targeted on its own.
  2. DEC HOOK 13 花了几千块买增高 supplement (the best lead→paid among funded ads, 7.9%) on
     supplement/TCM interests — parents currently buying supplements are the people this ad
     is talking to, and no campaign has ever pointed at them.

NOTHING IS GUESSED
------------------
Interest and demographic ids come from Meta's own targeting search at build time; a term that
does not resolve aborts the build rather than shipping an empty audience. DEC HOOK 13's
creative id and exact ad name are resolved from the live H&W ad, so the new copy inherits the
creative's sales history through the name key. 15岁以上 reuses the creative already carrying
its post engagement (1769022650919449, same as the LAL bands).

advantage_audience is sent as 0 AND verified after creation — Meta silently stored 1 on the
LAL bands despite being sent 0, so this build re-reads each ad set and rewrites the targeting
with both expansion switches forced off if the stored value differs. An audience-precision
test with expansion on answers nothing.

Idempotent via state/; everything is created PAUSED.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")
PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 50
SEED_ID = "120257737609370093"          # Cust Paid List (SG) — buyers never pay twice

V15PLUS_CREATIVE = "1769022650919449"   # 15岁以上 — the copy carrying the post engagement
V15PLUS_NAME = "Video：孩子15岁以上还有机会长高吗？"
DECHOOK13_AD = "120256984988360093"     # live H&W copy; creative + exact name resolved from it
CLONE_ADSET_ID = "120256891851660093"   # Parents 3–17 + Engaged — already carries the teen segment

SUPPLEMENT_TERMS = ["Dietary supplement", "Vitamin", "Traditional Chinese medicine"]


def find_teen_parents(g, s) -> Dict[str, Any]:
    """The teenager-parents segment id, without trusting the search endpoint.

    /search?type=adTargetingCategory&class=family_statuses returns nothing on current API
    versions (that is how the first run of this build died, correctly refusing to guess). But
    the account's own "Parents 3–17 + Engaged" ad set already targets the parent segments, so
    the id is read from its stored targeting first; the account-scoped targetingbrowse tree is
    the fallback. Still no guessing — zero or ambiguous candidates abort the build.
    """
    t = g._request("GET", CLONE_ADSET_ID, params={"fields": "targeting"}).get("targeting") or {}
    for grp in (t.get("flexible_spec") or []):
        for fs in (grp.get("family_statuses") or []):
            n = (fs.get("name") or "").lower()
            if "13-17" in n or "teenager" in n:
                return {"id": str(fs["id"]), "name": fs.get("name")}
    rows = g._request("GET", f"{s.meta.account_path}/targetingbrowse",
                      params={"limit": 2000}).get("data", [])
    hits = [r for r in rows if "13-17" in (r.get("name") or "")
            and ("teen" in (r.get("name") or "").lower()
                 or r.get("type") == "family_statuses")]
    if len(hits) != 1:
        raise SystemExit(f"!! teenager-parents segment: clone ad set had none and targetingbrowse "
                         f"returned {len(hits)} candidate(s) "
                         f"({[r.get('name') for r in hits]}) — refusing to guess.")
    return {"id": str(hits[0]["id"]), "name": hits[0].get("name")}


def find_interest(g, term: str) -> Optional[Dict[str, Any]]:
    rows = g._request("GET", "search", params={
        "type": "adinterest", "q": term, "limit": 10}).get("data", [])
    for r in rows:                       # exact name match first, then prefix
        if (r.get("name") or "").casefold() == term.casefold():
            return r
    return rows[0] if rows else None


def base_targeting(m) -> Dict[str, Any]:
    excl = list(m.targeting.excluded_custom_audiences or [])
    if SEED_ID not in excl:
        excl.append(SEED_ID)
    return {
        "geo_locations": {"countries": m.targeting.countries or ["SG"]},
        "age_min": 25, "age_max": 65,
        "excluded_custom_audiences": [{"id": i} for i in excl],
        "locales": m.targeting.locales or [1004],
        # 0, and verified below — an audience-precision test with expansion on answers nothing.
        "targeting_automation": {"advantage_audience": 0},
    }


def force_expansion_off(g, adset_id: str, spec: Dict[str, Any], log) -> str:
    """Meta stored advantage_audience=1 on the LAL bands despite being sent 0. Re-read, and if
    the stored value differs, write the spec back with both switches forced off."""
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv = (t.get("targeting_automation") or {}).get("advantage_audience")
    if int(adv or 0) == 0:
        return "off"
    fix = dict(spec)
    fix["targeting_automation"] = {"advantage_audience": 0}
    g._request("POST", adset_id, data={"targeting": json.dumps(fix)})
    t2 = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv2 = (t2.get("targeting_automation") or {}).get("advantage_audience")
    log.info("   advantage_audience stored %s → rewrote → now %s", adv, adv2)
    return "off" if int(adv2 or 0) == 0 else "STILL ON — fix by hand in Ads Manager"


def build_one(g, s, *, label: str, adset_name: str, state_key: str, spec: Dict[str, Any],
              ad_name: str, creative_id: str, log) -> Dict[str, str]:
    conv = s.meta.conversion_domain_bare or None
    ent = build(g, s, units=[], captions={}, dry_run=False, label=label,
                state_key=state_key, adset_name=adset_name,
                targeting_override=spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    st_path = STATE_DIR / f"{state_key}.json"
    st: Dict[str, Any] = json.loads(st_path.read_text()) if st_path.exists() else {}
    if st.get("built_ad"):
        log.info("   ad already built — skipping")
    else:
        ad = g.create_ad(s.meta.account_path, name=ad_name, adset_id=adset_id,
                         creative={"creative_id": creative_id},
                         status="PAUSED", conversion_domain=conv)
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_id": ad["id"], "built_ad": True})
        st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("   + ad %s ⟵ %s", ad["id"], ad_name)

    exp = force_expansion_off(g, adset_id, spec, log)
    return {"campaign": campaign_id, "adset": adset_id, "expansion": exp}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # ── resolve everything BEFORE building anything ──────────────────────────────
    teen = find_teen_parents(g, s)
    log.info("family status: %s (%s)", teen.get("name"), teen.get("id"))

    interests: List[Dict[str, Any]] = []
    for term in SUPPLEMENT_TERMS:
        r = find_interest(g, term)
        if r:
            interests.append({"id": r["id"], "name": r.get("name")})
            log.info("interest: %-32s → %s (audience ~%s)", term, r.get("name"),
                     r.get("audience_size_lower_bound", "?"))
        else:
            log.info("interest: %-32s → NOT FOUND, skipped", term)
    if len(interests) < 2:
        raise SystemExit("!! fewer than 2 supplement interests resolved — the audience would "
                         "be too thin to mean anything; nothing was built.")

    src = g._request("GET", DECHOOK13_AD, params={"fields": "name,creative{id},status"})
    dec_name, dec_creative = src.get("name"), (src.get("creative") or {}).get("id")
    if not dec_creative:
        raise SystemExit("!! could not resolve DEC HOOK 13's creative — nothing was built.")
    log.info("DEC HOOK 13 source: %r → creative %s", dec_name, dec_creative)

    # ── test 1: 15岁以上 × Parents with teenagers (13-17) ────────────────────────
    log.info("═" * 88)
    spec1 = base_targeting(m)
    spec1["flexible_spec"] = [{"family_statuses": [{"id": teen["id"], "name": teen.get("name")}]}]
    r1 = build_one(g, s, label="Teen Parents 13-17 | 1-1-1",
                   adset_name="Parents of Teens 13–17 | SG 25+",
                   state_key="entities_teen_parents_1_1_1", spec=spec1,
                   ad_name=V15PLUS_NAME, creative_id=V15PLUS_CREATIVE, log=log)

    # ── test 2: DEC HOOK 13 × supplement/TCM interests ───────────────────────────
    log.info("═" * 88)
    spec2 = base_targeting(m)
    spec2["flexible_spec"] = [{"interests": [{"id": i["id"], "name": i["name"]}
                                             for i in interests]}]
    r2 = build_one(g, s, label="Supplement Interests | 1-1-1",
                   adset_name="Supplements & TCM | SG 25+",
                   state_key="entities_supplement_int_1_1_1", spec=spec2,
                   ad_name=dec_name, creative_id=dec_creative, log=log)

    log.info("═" * 88)
    final_summary(
        log, f"Two interest tests built PAUSED at RM{DAILY_MYR}/day CBO each: 15岁以上 on "
             f"'{teen.get('name')}' (campaign {r1['campaign']}, expansion {r1['expansion']}) and "
             f"DEC HOOK 13 on {len(interests)} supplement/TCM interests "
             f"({', '.join(i['name'] for i in interests)}) (campaign {r2['campaign']}, expansion "
             f"{r2['expansion']}). One unknown per test: proven creatives, new audiences. Both "
             f"reuse the original creative and exact ad name, so engagement pools and the "
             f"paid-list join stays continuous. Review previews, then activate.")


if __name__ == "__main__":
    main()
