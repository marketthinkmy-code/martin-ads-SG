"""新账户在投结构全量细节导出 (read-only, 29 Sep).

Operator: 把我广告开的这些 campaign - ad set - ad list 出来 in details，MY 那边照抄。
Also feeds the H&W build: the four hand-built 1-3-3 campaigns' exact shape.

Every ACTIVE campaign on act_1179668409969241, fully expanded:
  campaign: name · objective · budget mode · special/regional flags
  ad set:   name · daily budget · optimization/billing/bid · promoted_object (pixel+event)
            targeting: geo · age · gender · locales · Adv+ · flexible_spec (interests/
            behaviors/demographics by name) · custom/excluded audiences by NAME · placements
  ad:       name · status · post id (effective_object_story_id) · url_tags (first ad only)
Read-only.
"""
from __future__ import annotations

import json

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    aud_names = {}
    try:
        aud_names = {str(a["id"]): a.get("name") for a in g._get_all(
            f"{NEW_ACCT}/customaudiences", {"fields": "id,name", "limit": 200})}
    except GraphError:
        pass

    camps = [c for c in g._get_all(
        f"{NEW_ACCT}/campaigns",
        {"fields": "id,name,status,effective_status,objective,daily_budget,"
                   "special_ad_categories,is_adset_budget_sharing_enabled", "limit": 200})
        if c.get("effective_status") == "ACTIVE"]
    adsets = g._get_all(
        f"{NEW_ACCT}/adsets",
        {"fields": "id,name,status,campaign_id,daily_budget,optimization_goal,"
                   "billing_event,bid_strategy,promoted_object,targeting", "limit": 500})
    ads = g._get_all(
        f"{NEW_ACCT}/ads",
        {"fields": "id,name,status,effective_status,adset_id,"
                   "creative{effective_object_story_id,url_tags}", "limit": 500})
    by_camp: dict = {}
    for a in adsets:
        by_camp.setdefault(a.get("campaign_id"), []).append(a)
    by_set: dict = {}
    for a in ads:
        by_set.setdefault(a.get("adset_id"), []).append(a)

    shown_tags = False
    n_sets = n_ads = 0
    for c in sorted(camps, key=lambda x: x.get("name") or ""):
        log.info("═" * 112)
        log.info("CAMPAIGN %r", c.get("name"))
        log.info("  objective %s · 预算 %s · id %s", c.get("objective"),
                 f"CBO RM{int(c.get('daily_budget') or 0) // 100}/day"
                 if c.get("daily_budget") else "ABO(预算在 ad set)", c["id"])
        for aset in by_camp.get(c["id"], []):
            if aset.get("status") != "ACTIVE":
                continue
            n_sets += 1
            t = aset.get("targeting") or {}
            po = aset.get("promoted_object") or {}
            geo = (t.get("geo_locations") or {})
            genders = t.get("genders")
            log.info("  ── AD SET %r · RM%d/day · id %s", aset.get("name"),
                     int(aset.get("daily_budget") or 0) // 100, aset["id"])
            log.info("     opt %s · billing %s · bid %s · pixel %s event %s",
                     aset.get("optimization_goal"), aset.get("billing_event"),
                     aset.get("bid_strategy"), po.get("pixel_id"),
                     po.get("custom_event_type"))
            log.info("     geo %s · age %s-%s · gender %s · locales %s · Adv+ %s",
                     geo.get("countries") or geo, t.get("age_min"), t.get("age_max"),
                     {None: "全部", 1: "男", 2: "女"}.get(
                         (genders or [None])[0], genders), t.get("locales"),
                     (t.get("targeting_automation") or {}).get("advantage_audience"))
            for i, spec in enumerate(t.get("flexible_spec") or [], 1):
                parts = []
                for kind, entries in spec.items():
                    names = ", ".join(e.get("name", e.get("id", "?")) for e in entries)
                    parts.append(f"{kind}: {names}")
                log.info("     兴趣组%d（AND） %s", i, " | ".join(parts))
            for f, label in (("custom_audiences", "包含受众"),
                             ("excluded_custom_audiences", "排除受众")):
                ents = t.get(f) or []
                if ents:
                    log.info("     %s: %s", label,
                             ", ".join(f"{aud_names.get(str(e.get('id')), '?')}"
                                       f"({e.get('id')})" for e in ents))
            pp = t.get("publisher_platforms")
            log.info("     版位: %s", "Advantage+（自动）" if not pp else
                     f"{pp} · fb {t.get('facebook_positions')} · ig {t.get('instagram_positions')}")
            for ad in by_set.get(aset["id"], []):
                if ad.get("status") != "ACTIVE":
                    continue
                n_ads += 1
                cr = ad.get("creative") or {}
                log.info("       ▸ AD %r · post %s", ad.get("name"),
                         cr.get("effective_object_story_id"))
                if not shown_tags and cr.get("url_tags"):
                    log.info("         url_tags(全部广告同款): %s", cr.get("url_tags"))
                    shown_tags = True
    final_summary(log, f"{len(camps)} active campaigns · {n_sets} active ad sets · "
                       f"{n_ads} active ads dumped in full detail. Read-only.")


if __name__ == "__main__":
    main()
