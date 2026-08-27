"""Split Parents 兴趣定向 | 1-1-4 into four 1-1-1 ABO pods — 每个广告都花到钱.

Operator's call (27 Aug): "这个 campaign 不要 1-1-4 了 … 我要用回我最原始的方法 1-1-1 abo，
make sure 每个广告都花到钱", budget "RM50/ AD SET" from the message it superseded.

Under the old CBO, Meta concentrated the RM100/day into whichever of the four ads it liked
(Video 13/15 delivering, 14/11 starved) — the exact opposite of what the operator wants now.
A CBO campaign cannot be switched to ABO in place (Meta rejects the edit), so this creates
FOUR new 1 campaign + 1 ad set + 1 ad pods, ABO, RM50/day on each ad set: every ad owns its
own budget, so every ad spends.

Nothing else changes: targeting is cloned by id from the source's own ad set (Parents 3–17 +
Engaged, 120256891851660093) including its advantage_audience value, and each ad reuses its
EXACT historical name + the creative currently bound to the original ad — sales attribution
is keyed to ad names, so the split inherits each video's history seamlessly.

Two modes via ADBOT_MODE:
  build   (default) — create the four pods, everything PAUSED for review. The source
                      campaign keeps running untouched (Video 13/15 are live today; pausing
                      it before the pods are approved would just create a delivery gap).
  cutover           — after review: activate all four pods, THEN pause the source campaign.
                      New first, old second — a few minutes of overlap beats a gap.

Guards: the source campaign's ad list is re-read and must match the four pinned ids exactly
(count check — if the team added/removed an ad, this list is stale and the run refuses);
creative ids resolve from the LIVE binding (a copy swap on the original wins over the pin);
audience-expansion drift is re-read and rewritten if Meta flips it (LAL-band lesson); stored
ad-set budgets are re-read — Meta bumps sub-floor budgets silently (RM30→RM100 on the LAL
bands), so what's STORED is reported, not what was sent. Idempotent per pod via state/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

SOURCE_CAMPAIGN = "120256891851180093"   # Parents 兴趣定向 | 1-1-4 · CBO RM100/day
CLONE_ADSET_ID = "120256891851660093"    # its single ad set: Parents 3–17 + Engaged
PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 50                           # operator: "RM50/ AD SET"

# Pinned 27 Aug from the live campaign. The run re-reads and refuses on any drift.
UNITS: List[Dict[str, str]] = [
    {"key": "video13", "ad": "120256891856130093", "creative": "1384215930283487",
     "label": "Video 13 三年前他長了10公分"},
    {"key": "video15", "ad": "120256899218410093", "creative": "981570714910715",
     "label": "Video 15 不到160慌了"},
    {"key": "video14", "ad": "120256894654280093", "creative": "1050765014385282",
     "label": "Video 14 身高停在小學"},
    {"key": "video11", "ad": "120256891853620093", "creative": "2230871977707871",
     "label": "Video 11 孩子來MC了"},
]

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def state_path(key: str) -> Path:
    return Path("state") / f"entities_p111_{key}.json"


def clone_from_adset(g, adset_id: str, s) -> Dict[str, Any]:
    """Faithful clone of the source ad set's targeting, forced to this market's geo.

    advantage_audience is cloned as stored — the pods must run the SAME audience the four
    ads run today, so the split changes exactly one thing (budget structure).
    """
    src = g._request("GET", adset_id, params={"fields": "name,targeting"})
    t = src.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:        # Meta rejects a higher hard floor when Advantage+ is on
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": {"countries": s.meta.targeting.countries or ["SG"]},
        "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": [{"id": i} for i in
                                      (s.meta.targeting.excluded_custom_audiences or [])],
        "locales": s.meta.targeting.locales or [1004],
    }
    if t.get("genders"):
        spec["genders"] = t["genders"]
    fs = t.get("flexible_spec")
    if fs:
        spec["flexible_spec"] = fs
    else:
        legacy = {k: t[k] for k in DETAIL_KEYS if t.get(k)}
        if legacy:
            spec["flexible_spec"] = [legacy]
    return {"spec": spec, "name": src.get("name"), "adv": adv}


def verify_expansion(g, adset_id: str, spec: Dict[str, Any], intended_adv: int, log) -> str:
    """Meta stored advantage_audience=1 on the LAL bands despite being sent 0 — when the
    source runs with expansion OFF, re-read the pod and rewrite if the stored value drifted."""
    if intended_adv != 0:
        return "on (cloned from source)"
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv = int((t.get("targeting_automation") or {}).get("advantage_audience") or 0)
    if adv == 0:
        return "off"
    fix = dict(spec)
    fix["targeting_automation"] = {"advantage_audience": 0}
    g._request("POST", adset_id, data={"targeting": json.dumps(fix)})
    t2 = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv2 = int((t2.get("targeting_automation") or {}).get("advantage_audience") or 0)
    log.info("   expansion drifted (adv=%s) → rewrote → adv=%s", adv, adv2)
    return "off" if adv2 == 0 else "STILL ON — fix by hand before activating"


def read_source_ads(g) -> Dict[str, Dict[str, Any]]:
    """Re-read the source campaign and refuse on ANY drift from the pinned four."""
    log = get_logger()
    ads = g._get_all(f"{SOURCE_CAMPAIGN}/ads",
                     {"fields": "id,name,status,effective_status,creative{id}", "limit": 100})
    live = {a["id"]: a for a in ads}
    pinned = {u["ad"] for u in UNITS}
    if set(live) != pinned:
        raise SystemExit(f"!! source campaign ads drifted: pinned {sorted(pinned)} vs live "
                         f"{sorted(live)} — the split list is stale, refusing to build.")
    for u in UNITS:
        a = live[u["ad"]]
        cur = str((a.get("creative") or {}).get("id") or "")
        if cur and cur != u["creative"]:
            log.warning("   creative on %s drifted %s → %s — using the LIVE binding",
                        u["label"], u["creative"], cur)
    return live


def do_build() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    s.naming.prefix = PREFIX
    s.meta.budget.level = "ADSET"                    # ABO — budget lives on each ad set
    s.meta.budget.daily_amount_myr = DAILY_MYR

    live = read_source_ads(g)
    src_camp = g._request("GET", SOURCE_CAMPAIGN,
                          params={"fields": "name,status,daily_budget"})
    log.info("── source %s %r · status=%s · CBO daily=%s — left untouched in build mode",
             SOURCE_CAMPAIGN, src_camp.get("name"), src_camp.get("status"),
             src_camp.get("daily_budget"))

    cloned = clone_from_adset(g, CLONE_ADSET_ID, s)
    spec, intended_adv = cloned["spec"], cloned["adv"]
    detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                 for k in DETAIL_KEYS)
    log.info("── targeting ← ad set %s %r (age %s-%s · adv=%s · %d detail entries)",
             CLONE_ADSET_ID, cloned["name"], spec["age_min"], spec["age_max"],
             intended_adv, detail)

    rows: List[str] = []
    for u in UNITS:
        log.info("═" * 88)
        log.info("── pod %s", u["label"])
        ent = build(g, s, units=[], captions={}, dry_run=False,
                    label=f"{u['label']} | 1-1-1", state_key=f"entities_p111_{u['key']}",
                    adset_name=f"Parents 3–17 + Engaged | {u['label']}",
                    targeting_override=spec)
        campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

        exp = verify_expansion(g, adset_id, spec, intended_adv, log)

        p = state_path(u["key"])
        st: Dict[str, Any] = json.loads(p.read_text()) if p.exists() else {}
        if st.get("split_ad_id"):
            ad_id = st["split_ad_id"]
            log.info("   ad already built (%s) — skipping", ad_id)
        else:
            a = live[u["ad"]]
            creative_id = str((a.get("creative") or {}).get("id") or u["creative"])
            ad = g.create_ad(acct, name=a["name"], adset_id=adset_id,
                             creative={"creative_id": creative_id},
                             status="PAUSED", conversion_domain=conv)
            ad_id = ad["id"]
            st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                       "split_ad_id": ad_id, "ad_name": a["name"],
                       "creative_id": creative_id, "source_ad_id": u["ad"]})
            p.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("   + ad %s %r (creative %s reused)", ad_id, a["name"], creative_id)

        stored = g._request("GET", adset_id,
                            params={"fields": "daily_budget,bid_strategy,status"})
        budget_note = f"RM{int(stored.get('daily_budget') or 0) / 100:.0f}"
        if str(stored.get("daily_budget")) != str(DAILY_MYR * 100):
            budget_note += f" (Meta floor bumped the sent RM{DAILY_MYR})"
        log.info("   campaign=%s adset=%s ad=%s · stored budget %s · expansion %s",
                 campaign_id, adset_id, ad_id, budget_note, exp)
        rows.append(f"{u['label']}: {budget_note}")

    log.info("═" * 88)
    final_summary(
        log, f"4 pods built PAUSED, one per ad, ABO with its own ad-set budget "
             f"({'; '.join(rows)}) — 每个广告都有自己的钱包, no CBO to starve anyone. Same "
             f"audience (cloned from Parents 3–17 + Engaged), same ad names and creatives, so "
             f"attribution history carries over. The source 1-1-4 campaign is STILL RUNNING "
             f"untouched (Video 13/15 live) — review the pods in Ads Manager, then dispatch "
             f"this workflow with mode=cutover to activate all four and pause the old campaign "
             f"in one shot.")


def do_cutover() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    pods: List[Dict[str, Any]] = []
    for u in UNITS:
        p = state_path(u["key"])
        if not p.exists():
            raise SystemExit(f"!! no state for pod {u['label']} — run build mode first.")
        st = json.loads(p.read_text())
        if not st.get("split_ad_id"):
            raise SystemExit(f"!! pod {u['label']} has no ad — run build mode first.")
        pods.append({**st, "label": u["label"]})

    # new first, old second — overlap over gap
    lit: List[str] = []
    for pod in pods:
        for ent in (pod["split_ad_id"], pod["adset_id"], pod["campaign_id"]):
            cur = g._request("GET", ent, params={"fields": "status"})
            if cur.get("status") != "ACTIVE":
                g._request("POST", ent, data={"status": "ACTIVE"})
        fin = g._request("GET", pod["split_ad_id"],
                         params={"fields": "status,effective_status"})
        ok = fin.get("effective_status") in ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
        log.info("── %s: ad %s effective=%s %s", pod["label"], pod["split_ad_id"],
                 fin.get("effective_status"), "ok" if ok else "!! NOT DELIVERABLE")
        if ok:
            lit.append(pod["label"])

    g._request("POST", SOURCE_CAMPAIGN, data={"status": "PAUSED"})
    after = g._request("GET", SOURCE_CAMPAIGN, params={"fields": "status"})
    old_off = after.get("status") == "PAUSED"
    log.info("── source campaign %s → %s", SOURCE_CAMPAIGN, after.get("status"))

    final_summary(
        log, f"cutover: {len(lit)}/{len(pods)} pods live ({'; '.join(lit)}), each on its own "
             f"RM-per-ad-set budget; the old 1-1-4 CBO campaign is "
             f"{'PAUSED' if old_off else 'STILL ' + str(after.get('status')) + ' — pause by hand'}. "
             f"每个广告现在都有自己的预算在花钱.")


def main() -> None:
    mode = (os.environ.get("ADBOT_MODE") or "build").strip().lower()
    if mode == "cutover":
        do_cutover()
    elif mode == "build":
        do_build()
    else:
        raise SystemExit(f"!! unknown ADBOT_MODE {mode!r} (build | cutover)")


if __name__ == "__main__":
    main()
