"""Two new ABO test ad sets on SG老户, RM50 each (operator 19 Nov 「60/40，两个都建，RM50」).

  V10HW  Video 10：不是吃不够，是吸收不到 → Health & Wellness
         campaign 120259499592070093 「[SG] 儿童长高方程式 | Health & Wellness | 11月新片7支 | 1-7-7」
         post of 11月新片B ad 120259531550250093; targeting from Health & Wellness ad set 120259499602510093.
         Evidence: Video 10 SG CPL RM38.28, MY RM45.24; Health & Wellness is SG's cheapest audience (饭桌 RM33.39).
  V5PAR  Video 5：饭桌生活细节场景 → Parents 3-17 + Engaged（女）
         campaign 120259531545720093 「[SG] 儿童长高方程式 | Parents 3-17 + Engaged（女） | 11月新片B 5支 | 1-5-5」
         post of Health & Wellness ad 120259499603470093 (own sale 11/18); targeting from Video 10's ad set
         120259531549750093. Evidence: Video 10 CPL RM38.28 on this audience; 饭桌 never tested on it.
Both campaigns are ABO, ACTIVE, and in config kpi.cpl_min_spend_overrides (「11月新片7支」 / 「11月新片B」, rule 9).
Targeting goes through apply_sg_build_defaults(); bid / optimization copied from the template ad set; url_tags from
config. ADBOT_MODE=check (default, read-only) / go (build + read back). ADBOT_ONLY=V10HW|V5PAR limits to one.
Idempotent via state/entities_two_1119.json.
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
DAILY_MINOR = 5000
STATE = Path("state") / "entities_two_1119.json"
BUILDS = {
    "V10HW": {"campaign": "120259499592070093", "template": "120259499602510093", "source_ad": "120259531550250093",
              "ad_name": "Video 10：不是吃不够，是吸收不到", "adset_name": "Health & Wellness"},
    "V5PAR": {"campaign": "120259531545720093", "template": "120259531549750093", "source_ad": "120259499603470093",
              "ad_name": "Video 5：饭桌生活细节场景", "adset_name": "Parents 3-17 + Engaged（女）"},
}


def main() -> None:
    log = get_logger()
    s = load_settings()
    m = s.meta
    g = graph_client(s)
    mode = (os.environ.get("ADBOT_MODE") or "check").strip().lower()
    only = (os.environ.get("ADBOT_ONLY") or "").strip().upper()
    keys = [only] if only in BUILDS else list(BUILDS)
    acct_bare = ACCT.replace("act_", "")

    plan = {}
    for key in keys:
        b = BUILDS[key]
        c = g.get_object(b["campaign"], "name,account_id,status,effective_status,daily_budget")
        if str(c.get("account_id")) != acct_bare or c.get("daily_budget"):
            log.error("❌ %s campaign %s 不在 SG老户或不是 ABO，停止，什么都没建。", key, b["campaign"])
            sys.exit(1)
        tpl = g.get_object(b["template"], "name,account_id,campaign_id,targeting,promoted_object,optimization_goal,"
                                          "billing_event,bid_strategy")
        if str(tpl.get("account_id")) != acct_bare:
            log.error("❌ %s 模板 ad set %s 不在 SG老户，停止。", key, b["template"])
            sys.exit(1)
        t = apply_sg_build_defaults(copy.deepcopy(tpl.get("targeting") or {}))
        src = g.get_object(b["source_ad"], "name,account_id,effective_status,creative{effective_object_story_id,"
                                           "object_story_id,title}")
        cr = src.get("creative") or {}
        pid = cr.get("effective_object_story_id") or cr.get("object_story_id")
        if str(src.get("account_id")) != acct_bare or not pid:
            log.error("❌ %s 原广告 %s 读不到 post id，停止。", key, b["source_ad"])
            sys.exit(1)
        try:
            body = (g.get_object(pid, "message").get("message") or "").replace("\n", " / ")[:120]
        except Exception as exc:  # noqa: BLE001
            body = f"（读不到文案：{str(exc)[:60]}）"
        ints = [x.get("name") for fs in t.get("flexible_spec") or [] for x in fs.get("interests") or []]
        beh = [x.get("name") for fs in t.get("flexible_spec") or [] for x in fs.get("behaviors") or []]
        log.info("═" * 100)
        log.info("%s · campaign %s %r · %s / %s · ABO", key, b["campaign"], c.get("name"), c.get("status"),
                 c.get("effective_status"))
        log.info("   受众模板 ad set %s %r · %s-%s 岁 · 性别 %s · Adv+ 受众 %s · 地区 %s · 兴趣 %s · 行为 %s · 自定义 %s"
                 " · 排除 %s · 版位 %s · 出价 %s · 优化 %s", b["template"], tpl.get("name"), t.get("age_min"),
                 t.get("age_max"), t.get("genders") or "全部", (t.get("targeting_automation") or {}).get("advantage_audience"),
                 t.get("geo_locations"), "/".join(ints) or "—", "/".join(beh) or "—",
                 [x.get("name") for x in t.get("custom_audiences") or []] or "—",
                 [x.get("name") for x in t.get("excluded_custom_audiences") or []] or "—",
                 "自动" if not t.get("publisher_platforms") else t.get("publisher_platforms"), tpl.get("bid_strategy"),
                 tpl.get("optimization_goal"))
        log.info("   素材：原广告 %s %r [%s] → post %s · 标题 %s", b["source_ad"], src.get("name"),
                 src.get("effective_status"), pid, cr.get("title") or "（沿用 post）")
        log.info("   文案开头：%s", body)
        log.info("   新 ad set %r RM%d · 新广告 %r", b["adset_name"], DAILY_MINOR // 100, b["ad_name"])
        plan[key] = (b, tpl, t, pid)
    if mode != "go":
        final_summary(log, f"预检（只读）：{keys} 都读到。没有建任何东西。")
        return

    st = json.loads(STATE.read_text()) if STATE.exists() else {}

    def persist():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    built = []
    for key, (b, tpl, t, pid) in plan.items():
        e = st.setdefault(key, {})
        if not e.get("creative"):
            f = {"name": f"{b['ad_name']} · post", "object_story_id": pid}
            if m.url_tags:
                f["url_tags"] = m.url_tags
            e["creative"] = g.create_adcreative(ACCT, **f)["id"]
            persist()
            time.sleep(0.8)
        if not e.get("adset"):
            f = {"name": b["adset_name"], "campaign_id": b["campaign"], "daily_budget": DAILY_MINOR, "status": "ACTIVE",
                 "optimization_goal": tpl.get("optimization_goal"), "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                 "promoted_object": tpl.get("promoted_object") or {}, "targeting": t,
                 "bid_strategy": tpl.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"}
            if m.regional_regulated_categories:
                f["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                f["regional_regulation_identities"] = m.regional_regulation_identities
            e["adset"] = g.create_adset(ACCT, **f)["id"]
            persist()
            time.sleep(1.0)
        if not e.get("ad"):
            e["ad"] = g.create_ad(ACCT, name=b["ad_name"], adset_id=e["adset"], creative={"creative_id": e["creative"]},
                                  status="ACTIVE", conversion_domain=m.conversion_domain_bare or None)["id"]
            persist()
            time.sleep(1.5)
        c = g.get_object(b["campaign"], "status,effective_status")
        a_s = g.get_object(e["adset"], "name,status,effective_status,daily_budget")
        ad = g.get_object(e["ad"], "name,status,effective_status,creative{effective_object_story_id}")
        same = (ad.get("creative") or {}).get("effective_object_story_id") == pid
        log.info("读回 %s · campaign %s %s/%s · ad set %s %r RM%d %s/%s · ad %s %r %s/%s · %s", key, b["campaign"],
                 c.get("status"), c.get("effective_status"), e["adset"], a_s.get("name"),
                 int(a_s.get("daily_budget") or 0) // 100, a_s.get("status"), a_s.get("effective_status"), e["ad"],
                 ad.get("name"), ad.get("status"), ad.get("effective_status"), "同一个 post ✓" if same else "post 不一样 ✗")
        built.append(f"{key}: ad set {e['adset']} · ad {e['ad']}")
    final_summary(log, "建好 " + " | ".join(built))


if __name__ == "__main__":
    main()
