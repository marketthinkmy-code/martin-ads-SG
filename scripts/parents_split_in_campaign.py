"""Inside the EXISTING Parents 兴趣定向 campaign: one ad set per ad. Nothing new outside it.

Operator's correction (27 Aug): "我会自己调 abo 和 cbo，我不要新建，我要在 existing" — the four
separate 1-1-1 pod campaigns built earlier the same day are REJECTED and deleted first, and the
split happens as originally worded: "全部 duplicate ads set in same campaign".

So, in campaign 120256891851180093 only:
  · four new ad sets, each a faithful targeting clone of the campaign's own Parents 3–17 +
    Engaged ad set (advantage_audience as stored), each holding ONE ad — exact historical
    name + the creative currently bound to the original (attribution is keyed to ad names);
  · everything new is PAUSED; the original ad set and its four ads are NOT touched
    (Video 13/15 keep delivering — no gap, no surprise);
  · the ABO/CBO flip, the per-ad-set budgets, and the old-ad-set-off/new-ad-sets-on swap are
    the operator's own manual moves in Ads Manager, by their explicit call.

Budget on the new ad sets follows whatever the campaign is at run time: while it is CBO
(campaign daily_budget present) Meta rejects ad-set budgets, so none are sent; if the operator
has already flipped it to ABO, each new ad set carries RM50/day (their stated per-ad-set
number) + its own bid strategy, since Meta then requires it.

Idempotent via state/entities_parents_inplace.json; the pinned four ad ids are re-read from
the campaign and any drift refuses the run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.state import now_iso

CAMPAIGN = "120256891851180093"          # Parents 兴趣定向 — the ONLY campaign touched
SOURCE_ADSET = "120256891851660093"      # its Parents 3–17 + Engaged ad set (clone source)
DAILY_MYR = 50                           # only used if the campaign is already ABO at run time
STATE_PATH = Path("state") / "entities_parents_inplace.json"

# The four rejected 1-1-1 pod campaigns from the same morning — deleted before anything else.
REJECTED_POD_STATES = ["entities_p111_video13", "entities_p111_video15",
                       "entities_p111_video14", "entities_p111_video11"]

UNITS: List[Dict[str, str]] = [
    {"key": "video13", "ad": "120256891856130093", "label": "Video 13"},
    {"key": "video15", "ad": "120256899218410093", "label": "Video 15"},
    {"key": "video14", "ad": "120256894654280093", "label": "Video 14"},
    {"key": "video11", "ad": "120256891853620093", "label": "Video 11"},
]

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def delete_rejected_pods(g, log) -> int:
    """Remove the four pod campaigns the operator rejected. Deleting a campaign takes its ad
    set and ad with it; the creatives survive (they are shared with the original ads)."""
    gone = 0
    for key in REJECTED_POD_STATES:
        p = Path("state") / f"{key}.json"
        if not p.exists():
            continue
        st = json.loads(p.read_text())
        cid = st.get("campaign_id")
        if not cid or st.get("deleted"):
            gone += 1 if st.get("deleted") else 0
            continue
        cur = g._request("GET", cid, params={"fields": "name,effective_status"})
        if cur.get("effective_status") != "DELETED":
            g._request("POST", cid, data={"status": "DELETED"})
        chk = g._request("GET", cid, params={"fields": "effective_status"})
        ok = chk.get("effective_status") == "DELETED"
        log.info("── pod %s %r → %s", cid, cur.get("name"),
                 chk.get("effective_status") if ok else "!! STILL " + str(chk.get("effective_status")))
        if ok:
            st.update({"deleted": True, "deleted_at": now_iso(),
                       "deleted_reason": "operator: 我不要新建，我要在 existing"})
            p.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            gone += 1
    return gone


def clone_targeting(g, s) -> Dict[str, Any]:
    """Faithful clone of the source ad set's targeting — same audience, nothing reinterpreted."""
    t = g._request("GET", SOURCE_ADSET, params={"fields": "targeting"}).get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    spec: Dict[str, Any] = {
        "geo_locations": {"countries": s.meta.targeting.countries or ["SG"]},
        "age_min": int(t.get("age_min") or 25), "age_max": int(t.get("age_max") or 65),
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
    return spec


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    deleted = delete_rejected_pods(g, log)
    log.info("═" * 88)

    camp = g._request("GET", CAMPAIGN, params={
        "fields": "name,status,daily_budget,is_adset_budget_sharing_enabled"})
    is_cbo = bool(camp.get("daily_budget"))
    log.info("── campaign %s %r · status=%s · %s", CAMPAIGN, camp.get("name"),
             camp.get("status"),
             f"CBO RM{int(camp['daily_budget']) / 100:.0f}/day — no ad-set budgets sent, "
             f"budgets are yours to set when you flip to ABO" if is_cbo
             else f"ABO — each new ad set gets RM{DAILY_MYR}/day")

    ads = g._get_all(f"{CAMPAIGN}/ads",
                     {"fields": "id,name,status,creative{id}", "limit": 100})
    # only the four originals count — anything this script itself made carries its own adset
    live = {a["id"]: a for a in ads}
    pinned = {u["ad"] for u in UNITS}
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    own_new = {v.get("ad_id") for v in st.values() if isinstance(v, dict)}
    drift = set(live) - pinned - own_new
    if drift or not pinned <= set(live):
        raise SystemExit(f"!! campaign ads drifted (unexpected: {sorted(drift)} · missing: "
                         f"{sorted(pinned - set(live))}) — refusing to build from a stale list.")

    spec = clone_targeting(g, s)
    detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                 for k in DETAIL_KEYS)
    log.info("── targeting ← ad set %s (age %s-%s · adv=%s · %d detail entries)",
             SOURCE_ADSET, spec["age_min"], spec["age_max"],
             (spec.get("targeting_automation") or {}).get("advantage_audience"), detail)

    rows: List[str] = []
    for u in UNITS:
        log.info("─" * 60)
        a = live[u["ad"]]
        rec: Dict[str, Any] = st.get(u["key"]) or {}

        if rec.get("adset_id"):
            log.info("── %s: reuse ad set %s", u["label"], rec["adset_id"])
        else:
            fields: Dict[str, Any] = {
                "name": f"Parents 3–17 + Engaged | {a['name']}",
                "campaign_id": CAMPAIGN,
                "optimization_goal": m.optimization_goal, "billing_event": "IMPRESSIONS",
                "promoted_object": m.promoted_object, "targeting": spec, "status": "PAUSED",
            }
            if not is_cbo:
                fields["daily_budget"] = DAILY_MYR * 100
                fields["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            rec["adset_id"] = g.create_adset(acct, **fields)["id"]
            st[u["key"]] = rec
            STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("── %s: + ad set %s", u["label"], rec["adset_id"])

        if rec.get("ad_id"):
            log.info("   reuse ad %s", rec["ad_id"])
        else:
            creative_id = str((a.get("creative") or {}).get("id"))
            ad = g.create_ad(acct, name=a["name"], adset_id=rec["adset_id"],
                             creative={"creative_id": creative_id},
                             status="PAUSED", conversion_domain=conv)
            rec.update({"ad_id": ad["id"], "ad_name": a["name"], "creative_id": creative_id,
                        "source_ad_id": u["ad"]})
            st[u["key"]] = rec
            STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("   + ad %s %r (creative %s reused)", ad["id"], a["name"], creative_id)

        chk = g._request("GET", rec["adset_id"], params={"fields": "status,daily_budget"})
        budget = chk.get("daily_budget")
        rows.append(f"{u['label']}: adset {rec['adset_id']} "
                    f"({'RM%.0f/day' % (int(budget) / 100) if budget else 'budget on flip'})")
        log.info("   ad set status=%s · daily_budget=%s", chk.get("status"), budget)

    log.info("═" * 88)
    final_summary(
        log, f"{deleted}/4 rejected pod campaigns deleted. Inside the SAME campaign "
             f"{CAMPAIGN}: 4 new ad sets, one ad each, all PAUSED ({'; '.join(rows)}). The "
             f"original ad set and its ads were not touched — Video 13/15 keep running. Yours "
             f"in Ads Manager: flip CBO→ABO, set each new ad set's budget, switch the new four "
             f"on and the old ad set off.")


if __name__ == "__main__":
    main()
