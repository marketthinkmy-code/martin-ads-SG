"""11月新片7支 copied onto two more audiences, scheduled 12 Nov 00:00 MYT (operator 11 Nov).

Operator 11/11: 「campaign 建成跟 [SG] 儿童长高方程式 | Food and Drink + Milk | 11月新片7支 | 1-7-7 一样的结构，但是 ad set 是用
Interest: Family and Relationships；另一个 campaign 也是，但是 ad set 是用 Health & Wellness；每个 ad set 50；开始时间设在
11/12（星期四）00:00 MYT」 and 「用 existing post id 建」.
  · Account SG老户 act_1024930575770087 (rule 1). Per audience: one ABO campaign, 7 ad sets (one per video:
    Video 1/2/3/5/6/7/8), RM50 each, ad set start_time 2026-11-12T00:00:00+08:00 (account timezone
    Asia/Kuala_Lumpur), campaign / ad sets / ads ACTIVE so Meta starts them by itself at that time.
  · Ads reuse the existing page post of the same video in the Food and Drink + Milk campaign
    (120259458979710093): creative = object_story_id of that ad's effective_object_story_id, url_tags from config,
    so likes / comments carry over and the copy is the one the operator approved on 9 Nov.
  · Targeting cloned from an SG老户 ad set of that audience, then apply_sg_build_defaults():
      FR  Interest: Family and Relationships ← 120258845187670093 (Video 2：長高了17cm, own sale 10/14)
      HW  Health & Wellness                  ← 120256984987300093 (什麼樣的孩子, own sales 8/5 + 8/12)
  · Campaign names keep 「11月新片7支」 so config kpi.cpl_min_spend_overrides covers them (rule 9).
ADBOT_MODE=check (default): read-only — template targeting + the 7 post ids, nothing written.
ADBOT_MODE=go: build ADBOT_AUD (FR / HW / ALL), read back. Idempotent via state/entities_nov12_<aud>.json.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path

from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.sg_build_defaults import apply_sg_build_defaults

ACCT = "act_1024930575770087"
START = "2026-11-12T00:00:00+0800"
DAILY_MINOR = 5000
REF_ADSET = "120259458981350093"   # Food and Drink + Milk | 11月新片7支, Video 1 ad set: bid strategy to match
SOURCE_ADS = {  # Food and Drink + Milk | 11月新片7支 (campaign 120259458979710093), SG老户
    "1": "120259458984840093", "2": "120259458992280093", "3": "120259458998430093", "5": "120259459004440093",
    "6": "120259459008630093", "7": "120259459017220093", "8": "120259459021510093",
}
AUDS = {
    "FR": {"template": "120258845187670093", "adset": "Interest: Family and Relationships",
           "campaign": "[SG] 儿童长高方程式 | Family and Relationships | 11月新片7支 | 1-7-7",
           "state": Path("state") / "entities_nov12_fr.json"},
    "HW": {"template": "120256984987300093", "adset": "Health & Wellness",
           "campaign": "[SG] 儿童长高方程式 | Health & Wellness | 11月新片7支 | 1-7-7",
           "state": Path("state") / "entities_nov12_hw.json"},
}


def main() -> None:
    log = get_logger()
    s = load_settings()
    m = s.meta
    g = graph_client(s)
    mode = (os.environ.get("ADBOT_MODE") or "check").strip().lower()
    which = (os.environ.get("ADBOT_AUD") or "ALL").strip().upper()
    keys = list(AUDS) if which == "ALL" else [which]
    log.info("SG老户 %s · 模式 %s · 受众 %s · 开始时间 %s", ACCT, mode, keys, START)

    # the 7 existing posts
    posts = {}
    for k, ad_id in SOURCE_ADS.items():
        a = g.get_object(ad_id, "name,effective_status,creative{id,effective_object_story_id,object_story_id}")
        cr = a.get("creative") or {}
        pid = cr.get("effective_object_story_id") or cr.get("object_story_id")
        if not pid:
            log.error("❌ Video %s ad %s 读不到 post id，停止，什么都没建。", k, ad_id)
            sys.exit(1)
        posts[k] = (a.get("name"), pid)
        log.info("  Video %s · 原广告 %s %r（%s）→ post %s", k, ad_id, a.get("name"), a.get("effective_status"), pid)

    tpls = {}
    for key in keys:
        cfg = AUDS[key]
        tpl = g.get_object(cfg["template"], "name,account_id,targeting,promoted_object,optimization_goal,billing_event,bid_strategy")
        if str(tpl.get("account_id")) != ACCT.replace("act_", ""):
            log.error("❌ 模板 %s 不在 SG老户，停止。", cfg["template"])
            sys.exit(1)
        t = apply_sg_build_defaults(copy.deepcopy(tpl.get("targeting") or {}))
        ints = [x.get("name") for fs in t.get("flexible_spec") or [] for x in fs.get("interests") or []]
        log.info("  %s 模板 %s %r · %s-%s 岁 · Adv+ 受众 %s · 地区 %s · 兴趣 %d 个：%s · 版位 自动", key, cfg["template"],
                 tpl.get("name"), t.get("age_min"), t.get("age_max"),
                 (t.get("targeting_automation") or {}).get("advantage_audience"), t.get("geo_locations"), len(ints),
                 "/".join(ints[:12]))
        tpls[key] = (tpl, t)
    ref = g.get_object(REF_ADSET, "bid_strategy,optimization_goal,billing_event,promoted_object")
    log.info("  出价照抄 Food and Drink + Milk 11月新片 ad set %s：bid_strategy %s · optimization %s · billing %s",
             REF_ADSET, ref.get("bid_strategy"), ref.get("optimization_goal"), ref.get("billing_event"))
    if mode != "go":
        final_summary(log, f"预检（只读）：7 个 post id 都读到；模板 {keys} 读到。没有建任何东西。")
        return

    conv = m.conversion_domain_bare or None
    out = []
    for key in keys:
        cfg = AUDS[key]
        tpl, t = tpls[key]
        path = cfg["state"]
        st = json.loads(path.read_text()) if path.exists() else {}

        def persist():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(st, ensure_ascii=False, indent=2))

        if not st.get("campaign_id"):              # a failed earlier run may have created it: reuse by exact name
            for c in g._get_all(f"{ACCT}/campaigns", {"fields": "id,name,effective_status", "limit": 200,
                                                      "filtering": json.dumps([{"field": "name", "operator": "EQUAL",
                                                                                "value": cfg["campaign"]}])}):
                if c.get("name") == cfg["campaign"] and c.get("effective_status") not in ("DELETED", "ARCHIVED"):
                    st["campaign_id"] = c["id"]
                    log.info("  %s 沿用上次建了一半的 campaign %s（%s）", key, c["id"], c.get("effective_status"))
                    for a_s in g._get_all(f"{c['id']}/adsets", {"fields": "id", "limit": 50}):
                        log.error("❌ %s campaign %s 里已经有 ad set %s，停止，免得重复。", key, c["id"], a_s["id"])
                        sys.exit(1)
                    persist()
                    break
        if not st.get("campaign_id"):
            f = {"name": cfg["campaign"], "objective": m.objective, "buying_type": "AUCTION", "status": "ACTIVE",
                 "special_ad_categories": m.special_ad_categories, "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                f["regional_regulated_categories"] = m.regional_regulated_categories
            st["campaign_id"] = g.create_campaign(ACCT, **f)["id"]
            persist()
            log.info("+ %s campaign %s %r ABO", key, st["campaign_id"], cfg["campaign"])
            time.sleep(1.0)
        for d in ("creatives", "adsets", "ads"):
            st.setdefault(d, {})
        for k, (name, pid) in posts.items():
            if not st["creatives"].get(k):
                f = {"name": f"{name} · post", "object_story_id": pid}
                if m.url_tags:
                    f["url_tags"] = m.url_tags
                st["creatives"][k] = g.create_adcreative(ACCT, **f)["id"]
                persist()
                time.sleep(0.8)
            if not st["adsets"].get(k):
                f = {"name": cfg["adset"], "campaign_id": st["campaign_id"], "daily_budget": DAILY_MINOR,
                     "status": "ACTIVE", "start_time": START,
                     "optimization_goal": ref.get("optimization_goal") or tpl.get("optimization_goal"),
                     "billing_event": ref.get("billing_event") or "IMPRESSIONS",
                     "promoted_object": ref.get("promoted_object") or tpl.get("promoted_object") or {}, "targeting": t,
                     "bid_strategy": ref.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"}
                if m.regional_regulated_categories:
                    f["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    f["regional_regulation_identities"] = m.regional_regulation_identities
                st["adsets"][k] = g.create_adset(ACCT, **f)["id"]
                persist()
                time.sleep(1.0)
            if not st["ads"].get(k):
                st["ads"][k] = g.create_ad(ACCT, name=name, adset_id=st["adsets"][k],
                                           creative={"creative_id": st["creatives"][k]}, status="ACTIVE",
                                           conversion_domain=conv)["id"]
                persist()
                time.sleep(0.8)

        c = g.get_object(st["campaign_id"], "name,status,effective_status")
        log.info("═" * 100)
        log.info("%s campaign %s %r · %s / %s", key, st["campaign_id"], c.get("name"), c.get("status"), c.get("effective_status"))
        for k, (name, pid) in posts.items():
            a_s = g.get_object(st["adsets"][k], "name,status,effective_status,daily_budget,start_time,targeting")
            ad = g.get_object(st["ads"][k], "name,status,effective_status,creative{effective_object_story_id}")
            tt = a_s.get("targeting") or {}
            same = (ad.get("creative") or {}).get("effective_object_story_id") == pid
            log.info("  Video %s · ad set %s %r RM%d %s/%s 开始 %s · 地区 %s · 版位 %s · ad %s %r %s/%s · post %s（跟原广告同一个：%s）",
                     k, st["adsets"][k], a_s.get("name"), int(a_s.get("daily_budget") or 0) // 100, a_s.get("status"),
                     a_s.get("effective_status"), a_s.get("start_time"), (tt.get("geo_locations") or {}).get("location_types"),
                     "自动" if not tt.get("publisher_platforms") else tt.get("publisher_platforms"), st["ads"][k],
                     ad.get("name"), ad.get("status"), ad.get("effective_status"),
                     (ad.get("creative") or {}).get("effective_object_story_id"), "✓" if same else "✗")
        out.append(f"{key} campaign {st['campaign_id']} · " + " | ".join(f"V{k} ad {st['ads'][k]}" for k in posts))
    final_summary(log, "建好（SG老户，11/12 00:00 MYT 开始）：" + " ‖ ".join(out))


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
