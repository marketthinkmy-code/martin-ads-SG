"""Two CBO 1-1-3 campaigns on SG老户 from the 6 picked creatives (operator 20 Nov: 「那 6 个视频，我想要做成两个 1:1:3：
前面 3 个 video 变成 1:1:3，后面 3 个 video 又变成一个 1:1:3」; proposal accepted 「就照我上一条的提案，可以」).

  1  「[SG] 儿童长高方程式 | 赢家 1-1-3 A | 1120」 CBO RM75 · ad set Family and Relationships (targeting from
     120259499590130093) · Video 5 饭桌 / Video 8 我跟你说 / Video 5 Kaya
  2  「[SG] 儿童长高方程式 | 赢家 1-1-3 B | 1120」 CBO RM75 · ad set Interest: Food and Drink + Milk (targeting from
     120259459018220093, paid-student audience added to the exclusions) · MAR Video 5 林書豪 / Hook 3 倒掉牛奶 /
     Video 10 吸收不到
Creative evidence: adbot-creative-pick run 44671191196; audience evidence: adbot-adset-sales-rank-1010 run 44679083254.
Existing posts (copy unchanged), url_tags from config, targeting through apply_sg_build_defaults(); optimization /
billing / promoted object from the template. Campaign names carry 「赢家」 (config kpi.cpl_min_spend_overrides, rule 9).
ADBOT_MODE=check (default, read-only) / go (build + read back). Idempotent via state/entities_two113_1120.json.
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
STATE = Path("state") / "entities_two113_1120.json"
PAID_AUDIENCE = {"id": "120246547080720093", "name": "马丁 1997 Paid Student"}
CAMPAIGNS = {
    "A": {"name": "[SG] 儿童长高方程式 | 赢家 1-1-3 A | 1120", "budget": 7500,
          "adset": ("Family and Relationships", "120259499590130093"),
          "ads": [("Video 5：饭桌生活细节场景", "120259499603470093"),
                  ("Video 8：对话式「我跟你说！」", "120259459021510093"),
                  ("Video 5：Kaya 面包配 Milo", "120250236477220335")]},
    "B": {"name": "[SG] 儿童长高方程式 | 赢家 1-1-3 B | 1120", "budget": 7500,
          "adset": ("Interest: Food and Drink + Milk", "120259459018220093"),
          "ads": [("MAR Video 5：林書豪story", "120250093193110335"),
                  ("Hook 3：倒掉牛奶", "120250013471210335"),
                  ("Video 10：不是吃不够，是吸收不到", "120259531550250093")]},
}


def main() -> None:
    log = get_logger()
    s = load_settings()
    m = s.meta
    g = graph_client(s)
    mode = (os.environ.get("ADBOT_MODE") or "check").strip().lower()

    plan = {}
    for ck, c in CAMPAIGNS.items():
        aname, tid = c["adset"]
        tpl = g.get_object(tid, "name,account_id,targeting,promoted_object,optimization_goal,billing_event")
        if str(tpl.get("account_id")) != ACCT.replace("act_", ""):
            log.error("❌ 模板 %s 不在 SG老户，停止，什么都没建。", tid)
            sys.exit(1)
        t = apply_sg_build_defaults(copy.deepcopy(tpl.get("targeting") or {}))
        exc = t.get("excluded_custom_audiences") or []
        if not any(str(x.get("id")) == PAID_AUDIENCE["id"] for x in exc):
            exc = exc + [dict(PAID_AUDIENCE)]
        t["excluded_custom_audiences"] = [{"id": str(x.get("id")), "name": x.get("name")} for x in exc]
        ints = [x.get("name") for fs in t.get("flexible_spec") or [] for k in ("interests", "behaviors")
                for x in fs.get(k) or []]
        log.info("═" * 100)
        log.info("Campaign %s · %r · CBO RM%d/天", ck, c["name"], c["budget"] // 100)
        log.info("   ad set %r · 照抄 %s %r · %s-%s 岁 · 性别 %s · Adv+ %s · 地区 %s · 版位 %s · 排除 %s · 优化 %s",
                 aname, tid, tpl.get("name"), t.get("age_min"), t.get("age_max"), t.get("genders") or "全部",
                 (t.get("targeting_automation") or {}).get("advantage_audience"),
                 (t.get("geo_locations") or {}).get("location_types"),
                 "自动" if not t.get("publisher_platforms") else t.get("publisher_platforms"),
                 [x.get("name") for x in t["excluded_custom_audiences"]], tpl.get("optimization_goal"))
        log.info("   兴趣/行为（%d 个）：%s", len(ints), "/".join(ints))
        ads = []
        for name, src in c["ads"]:
            a = g.get_object(src, "name,effective_status,creative{effective_object_story_id,object_story_id,title}")
            cr = a.get("creative") or {}
            pid = cr.get("effective_object_story_id") or cr.get("object_story_id")
            if not pid:
                log.error("❌ 原广告 %s 读不到 post id，停止，什么都没建。", src)
                sys.exit(1)
            log.info("   广告 %r ← 原广告 %s [%s] · post %s · 标题 %s", name, src, a.get("effective_status"), pid,
                     cr.get("title") or "—")
            ads.append((name, pid))
        plan[ck] = (c, tpl, t, ads)
    if mode != "go":
        final_summary(log, "预检（只读）：2 个受众模板、6 个 post 都读到。没有建任何东西。")
        return

    st = json.loads(STATE.read_text()) if STATE.exists() else {}

    def persist():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    conv = m.conversion_domain_bare or None
    for ck, (c, tpl, t, ads) in plan.items():
        e = st.setdefault(ck, {"creatives": {}, "ads": {}})
        if not e.get("campaign"):
            f = {"name": c["name"], "objective": m.objective, "buying_type": "AUCTION", "status": "ACTIVE",
                 "special_ad_categories": m.special_ad_categories, "daily_budget": c["budget"],
                 "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
            if m.regional_regulated_categories:
                f["regional_regulated_categories"] = m.regional_regulated_categories
            e["campaign"] = g.create_campaign(ACCT, **f)["id"]
            persist()
            time.sleep(1.0)
        if not e.get("adset"):
            f = {"name": c["adset"][0], "campaign_id": e["campaign"], "status": "ACTIVE",
                 "optimization_goal": tpl.get("optimization_goal"),
                 "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                 "promoted_object": tpl.get("promoted_object") or {}, "targeting": t}
            if m.regional_regulated_categories:
                f["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                f["regional_regulation_identities"] = m.regional_regulation_identities
            e["adset"] = g.create_adset(ACCT, **f)["id"]
            persist()
            time.sleep(1.0)
        for name, pid in ads:
            if not e["creatives"].get(name):
                f = {"name": f"{name} · post · 赢家 1120", "object_story_id": pid}
                if m.url_tags:
                    f["url_tags"] = m.url_tags
                e["creatives"][name] = g.create_adcreative(ACCT, **f)["id"]
                persist()
                time.sleep(0.8)
            if not e["ads"].get(name):
                e["ads"][name] = g.create_ad(ACCT, name=name, adset_id=e["adset"],
                                             creative={"creative_id": e["creatives"][name]}, status="ACTIVE",
                                             conversion_domain=conv)["id"]
                persist()
                time.sleep(0.8)

    log.info("═" * 100)
    for ck in plan:
        e = st[ck]
        cc = g.get_object(e["campaign"], "name,status,effective_status,daily_budget")
        a_s = g.get_object(e["adset"], "name,status,effective_status")
        log.info("读回 %s · campaign %s %r %s/%s CBO RM%d · ad set %s %r %s/%s", ck, e["campaign"], cc.get("name"),
                 cc.get("status"), cc.get("effective_status"), int(cc.get("daily_budget") or 0) // 100, e["adset"],
                 a_s.get("name"), a_s.get("status"), a_s.get("effective_status"))
        for name, adid in e["ads"].items():
            ad = g.get_object(adid, "name,status,effective_status")
            log.info("   ad %s %r %s/%s", adid, ad.get("name"), ad.get("status"), ad.get("effective_status"))
    final_summary(log, f"建好 A {st['A']['campaign']} · B {st['B']['campaign']}")


if __name__ == "__main__":
    main()
