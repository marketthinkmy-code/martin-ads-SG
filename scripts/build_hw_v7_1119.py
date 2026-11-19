"""Test Video 7：14歲了，還有機會長高嗎 on Health & Wellness, SG老户 (operator 19 Nov 「测吧」).

Why: US runs it cheap (operator screenshots RM38.74 → RM45.71); on SG it only had 2 days / RM84.87 / 1 registration
on Parents 3-17 + Engaged（女） (11月新片B ad 120259531547350093) — too little to judge. Health & Wellness is where
Video 5 饭桌 is cheapest on SG (RM33.39 lifetime, creative_life_1119 run 44471976578).

  · Account SG老户 act_1024930575770087 (rule 1: new film test on SG old, ABO, one film per ad set).
  · Campaign: existing ABO 120259499592070093 「[SG] 儿童长高方程式 | Health & Wellness | 11月新片7支 | 1-7-7」
    (name contains 「11月新片7支」, in config kpi.cpl_min_spend_overrides — rule 9).
  · New ad set "Health & Wellness", RM60 / day, ACTIVE now. Targeting cloned from the live Health & Wellness ad set
    120259499602510093 (Video 5 饭桌) then apply_sg_build_defaults(); bid / optimization copied from it.
  · Ad "Video 7：14歲了，還有機會長高嗎" reuses the existing page post of 120259531547350093 (copy already approved,
    likes / comments carry over), url_tags from config.
ADBOT_MODE=check (default): read-only — prints campaign, template targeting, the post and its copy. Nothing written.
ADBOT_MODE=go: build, read back. Idempotent via state/entities_hw_v7_1119.json.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.sg_build_defaults import apply_sg_build_defaults

ACCT = "act_1024930575770087"
CAMPAIGN = "120259499592070093"
TEMPLATE_ADSET = "120259499602510093"
SOURCE_AD = "120259531547350093"
AD_NAME = "Video 7：14歲了，還有機會長高嗎"
ADSET_NAME = "Health & Wellness"
DAILY_MINOR = 6000
STATE = Path("state") / "entities_hw_v7_1119.json"


def main() -> None:
    log = get_logger()
    s = load_settings()
    m = s.meta
    g = graph_client(s)
    mode = (os.environ.get("ADBOT_MODE") or "check").strip().lower()

    c = g.get_object(CAMPAIGN, "name,account_id,status,effective_status,daily_budget,objective")
    if str(c.get("account_id")) != ACCT.replace("act_", "") or c.get("daily_budget"):
        log.error("❌ campaign %s 不在 SG老户或不是 ABO（daily_budget=%s），停止。", CAMPAIGN, c.get("daily_budget"))
        sys.exit(1)
    log.info("campaign %s %r · %s / %s · ABO · %s", CAMPAIGN, c.get("name"), c.get("status"), c.get("effective_status"),
             c.get("objective"))
    for a_s in g._get_all(f"{CAMPAIGN}/ads", {"fields": "id,name,effective_status,adset{id,daily_budget}", "limit": 50}):
        log.info("   现有 ad %s %r [%s] · ad set %s RM%s", a_s["id"], a_s.get("name"), a_s.get("effective_status"),
                 (a_s.get("adset") or {}).get("id"), int((a_s.get("adset") or {}).get("daily_budget") or 0) // 100)

    tpl = g.get_object(TEMPLATE_ADSET, "name,account_id,targeting,promoted_object,optimization_goal,billing_event,"
                                       "bid_strategy,daily_budget")
    t = apply_sg_build_defaults(copy.deepcopy(tpl.get("targeting") or {}))
    ints = [x.get("name") for fs in t.get("flexible_spec") or [] for x in fs.get("interests") or []]
    log.info("模板 ad set %s %r · %s-%s 岁 · 性别 %s · Adv+ 受众 %s · 地区 %s · 兴趣 %d 个：%s · 版位 %s · 出价 %s · 优化 %s",
             TEMPLATE_ADSET, tpl.get("name"), t.get("age_min"), t.get("age_max"), t.get("genders") or "全部",
             (t.get("targeting_automation") or {}).get("advantage_audience"), t.get("geo_locations"), len(ints),
             "/".join(ints), "自动" if not t.get("publisher_platforms") else t.get("publisher_platforms"),
             tpl.get("bid_strategy"), tpl.get("optimization_goal"))

    src = g.get_object(SOURCE_AD, "name,account_id,effective_status,creative{id,effective_object_story_id,object_story_id,"
                                  "body,title}")
    cr = src.get("creative") or {}
    pid = cr.get("effective_object_story_id") or cr.get("object_story_id")
    if str(src.get("account_id")) != ACCT.replace("act_", "") or not pid:
        log.error("❌ 原广告 %s 不在 SG老户或读不到 post id，停止。", SOURCE_AD)
        sys.exit(1)
    log.info("原广告 %s %r [%s] → post %s", SOURCE_AD, src.get("name"), src.get("effective_status"), pid)
    body = cr.get("body") or ""
    if not body:
        try:
            body = g.get_object(pid, "message").get("message") or ""
        except Exception as exc:  # noqa: BLE001
            body = f"（读不到文案：{str(exc)[:80]}）"
    log.info("   文案开头：%s", body.replace("\n", " / ")[:160])
    log.info("   标题：%s", cr.get("title") or "（creative 上没有，沿用 post）")
    if mode != "go":
        final_summary(log, "预检（只读）：campaign、模板受众、post 都读到。没有建任何东西。")
        return

    st = json.loads(STATE.read_text()) if STATE.exists() else {}

    def persist():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    if not st.get("creative"):
        f = {"name": f"{AD_NAME} · post", "object_story_id": pid}
        if m.url_tags:
            f["url_tags"] = m.url_tags
        st["creative"] = g.create_adcreative(ACCT, **f)["id"]
        persist()
        time.sleep(0.8)
    if not st.get("adset"):
        f = {"name": ADSET_NAME, "campaign_id": CAMPAIGN, "daily_budget": DAILY_MINOR, "status": "ACTIVE",
             "optimization_goal": tpl.get("optimization_goal"), "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
             "promoted_object": tpl.get("promoted_object") or {}, "targeting": t,
             "bid_strategy": tpl.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"}
        if m.regional_regulated_categories:
            f["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            f["regional_regulation_identities"] = m.regional_regulation_identities
        st["adset"] = g.create_adset(ACCT, **f)["id"]
        persist()
        time.sleep(1.0)
    if not st.get("ad"):
        st["ad"] = g.create_ad(ACCT, name=AD_NAME, adset_id=st["adset"], creative={"creative_id": st["creative"]},
                               status="ACTIVE", conversion_domain=m.conversion_domain_bare or None)["id"]
        persist()
        time.sleep(1.5)

    c = g.get_object(CAMPAIGN, "status,effective_status")
    a_s = g.get_object(st["adset"], "name,status,effective_status,daily_budget,targeting")
    ad = g.get_object(st["ad"], "name,status,effective_status,creative{effective_object_story_id}")
    same = (ad.get("creative") or {}).get("effective_object_story_id") == pid
    log.info("═" * 100)
    log.info("读回 campaign %s %s/%s · ad set %s %r RM%d %s/%s 地区 %s · ad %s %r %s/%s · post %s %s", CAMPAIGN,
             c.get("status"), c.get("effective_status"), st["adset"], a_s.get("name"), int(a_s.get("daily_budget") or 0) // 100,
             a_s.get("status"), a_s.get("effective_status"), ((a_s.get("targeting") or {}).get("geo_locations") or {}).get(
                 "location_types"), st["ad"], ad.get("name"), ad.get("status"), ad.get("effective_status"),
             (ad.get("creative") or {}).get("effective_object_story_id"), "✓ 同一个 post" if same else "✗ post 不一样")
    final_summary(log, f"建好：ad set {st['adset']} RM{DAILY_MINOR // 100} · ad {st['ad']}")


if __name__ == "__main__":
    main()
