"""Generic in-campaign split: duplicate ONE ad set into one-ad-set-per-ad, same campaign.

The operator's standing instruction, applied campaign by campaign as they point at them:
"全部 duplicate ads set in same campaign, 分成 1-1-1 abo RM50/ AD SET 我要全部广告都均匀花到钱"
and, from the first application: "我会自己调 abo 和 cbo，我不要新建，我要在 existing".

So this script NEVER creates a campaign. Given a campaign id and its source ad set id
(both explicit inputs — nothing is guessed), it:
  · reads every ad currently in the source ad set (全部 — any status);
  · creates one new ad set per ad INSIDE the same campaign, cloning the source ad set's own
    targeting (advantage_audience as stored), optimization goal, billing event and promoted
    object, plus the account's SG regulated-category declarations;
  · puts one ad in each — exact historical name + the creative currently bound to the
    original (sales attribution is keyed to ad names);
  · leaves the source ad set and its ads completely untouched, and creates everything PAUSED.

Budgets: while the campaign is CBO (campaign daily_budget present) Meta rejects ad-set
budgets, so none are sent — the operator assigns them when they flip to ABO themselves. If
the campaign is already ABO at run time, each new ad set carries ADBOT_DAILY_MYR (default
RM50) + its own bid strategy, because Meta then requires one.

Inputs (env): ADBOT_CAMPAIGN_ID, ADBOT_SOURCE_ADSET_ID, ADBOT_DAILY_MYR (optional).
The source ad set must belong to the campaign or the run refuses — a mistyped pair must
fail loudly, not build into the wrong campaign.

Idempotent per campaign via state/entities_inplace_split_<campaign_id>.json, keyed by
source ad id — a re-dispatch reuses what exists and only adds what is missing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def clone_targeting(g, adset_id: str, s) -> Dict[str, Any]:
    """Faithful clone of the source ad set's audience — nothing reinterpreted."""
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
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
    return spec


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    campaign_id = (os.environ.get("ADBOT_CAMPAIGN_ID") or "").strip()
    source_adset = (os.environ.get("ADBOT_SOURCE_ADSET_ID") or "").strip()
    daily_myr = int(os.environ.get("ADBOT_DAILY_MYR") or 50)
    if not campaign_id or not source_adset:
        raise SystemExit("!! ADBOT_CAMPAIGN_ID and ADBOT_SOURCE_ADSET_ID are both required.")

    camp = g._request("GET", campaign_id, params={"fields": "name,status,daily_budget"})
    is_cbo = bool(camp.get("daily_budget"))
    budget_word = (f"CBO RM{int(camp['daily_budget']) / 100:.0f}/day — no ad-set budgets sent, "
                   f"yours to set on the ABO flip" if is_cbo
                   else f"ABO — each new ad set gets RM{daily_myr}/day")
    log.info("── campaign %s %r · status=%s · %s", campaign_id, camp.get("name"),
             camp.get("status"), budget_word)

    src = g._request("GET", source_adset, params={
        "fields": "name,campaign_id,status,optimization_goal,billing_event,promoted_object,"
                  "destination_type"})
    if str(src.get("campaign_id")) != campaign_id:
        raise SystemExit(f"!! ad set {source_adset} belongs to campaign {src.get('campaign_id')}, "
                         f"not {campaign_id} — mismatched inputs, refusing.")
    log.info("── source ad set %s %r · status=%s · goal=%s", source_adset, src.get("name"),
             src.get("status"), src.get("optimization_goal"))

    ads = g._get_all(f"{source_adset}/ads",
                     {"fields": "id,name,status,creative{id}", "limit": 200})
    if not ads:
        raise SystemExit(f"!! source ad set {source_adset} holds no ads — nothing to split.")
    log.info("── %d ads to split (全部): %s", len(ads),
             " · ".join(f"{a['name']}[{a.get('status')}]" for a in ads))

    others = [a for a in g._get_all(f"{campaign_id}/adsets", {"fields": "id,name", "limit": 200})
              if a["id"] != source_adset]

    spec = clone_targeting(g, source_adset, s)
    detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                 for k in DETAIL_KEYS)
    log.info("── targeting cloned (age %s-%s · adv=%s · %d detail entries)",
             spec["age_min"], spec["age_max"],
             (spec.get("targeting_automation") or {}).get("advantage_audience"), detail)

    st_path = Path("state") / f"entities_inplace_split_{campaign_id}.json"
    st: Dict[str, Any] = json.loads(st_path.read_text()) if st_path.exists() else {}
    st.setdefault("campaign_id", campaign_id)
    st.setdefault("source_adset", source_adset)
    units: Dict[str, Any] = st.setdefault("units", {})

    def persist() -> None:
        st_path.parent.mkdir(parents=True, exist_ok=True)
        st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    rows: List[str] = []
    for a in ads:
        log.info("─" * 60)
        rec: Dict[str, Any] = units.get(a["id"]) or {}

        if rec.get("adset_id"):
            log.info("── %s: reuse ad set %s", a["name"], rec["adset_id"])
        else:
            fields: Dict[str, Any] = {
                "name": f"{src.get('name')} | {a['name']}",
                "campaign_id": campaign_id,
                "optimization_goal": src.get("optimization_goal") or m.optimization_goal,
                "billing_event": src.get("billing_event") or "IMPRESSIONS",
                "promoted_object": src.get("promoted_object") or m.promoted_object,
                "targeting": spec, "status": "PAUSED",
            }
            if src.get("destination_type"):
                fields["destination_type"] = src["destination_type"]
            if not is_cbo:
                fields["daily_budget"] = daily_myr * 100
                fields["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            rec["adset_id"] = g.create_adset(acct, **fields)["id"]
            units[a["id"]] = rec
            persist()
            log.info("── %s: + ad set %s", a["name"], rec["adset_id"])

        if rec.get("ad_id"):
            log.info("   reuse ad %s", rec["ad_id"])
        else:
            creative_id = str((a.get("creative") or {}).get("id"))
            ad = g.create_ad(acct, name=a["name"], adset_id=rec["adset_id"],
                             creative={"creative_id": creative_id},
                             status="PAUSED", conversion_domain=conv)
            rec.update({"ad_id": ad["id"], "ad_name": a["name"], "creative_id": creative_id})
            units[a["id"]] = rec
            persist()
            log.info("   + ad %s %r (creative %s reused)", ad["id"], a["name"], creative_id)

        chk = g._request("GET", rec["adset_id"], params={"fields": "status,daily_budget"})
        b = chk.get("daily_budget")
        rows.append(f"{a['name']}: adset {rec['adset_id']} "
                    f"({'RM%.0f/day' % (int(b) / 100) if b else 'budget on flip'})")
        log.info("   ad set status=%s · daily_budget=%s", chk.get("status"), b)

    log.info("═" * 88)
    if others:
        log.info("note: campaign has %d other ad set(s) untouched: %s", len(others),
                 " · ".join(f"{o['id']} {o.get('name', '')[:40]}" for o in others))
    final_summary(
        log, f"campaign {campaign_id} {camp.get('name')!r}: {len(rows)} new ad sets inside the "
             f"SAME campaign, one ad each, all PAUSED ({'; '.join(rows)}). Source ad set "
             f"{source_adset} and its ads untouched. Yours in Ads Manager: flip CBO→ABO, set "
             f"each new ad set's budget, switch the new ones on and the old ad set off.")


if __name__ == "__main__":
    main()
