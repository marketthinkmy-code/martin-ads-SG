"""Two scale campaigns on SG老户 with proven creatives / audiences (operator 20 Nov 「建 两个 1-1-3 + CBO，给我 3 个成交转化
最好的 ad set 受众」; FAMILY swapped for Food & Drink + Milk + Bread 「我怕跟 Family and Relationships 撞」).

  A  1-1-3 ABO  「[SG] 儿童长高方程式 | 赢家 1-1-3 | 1120」
     ad set Family and Relationships RM60 (targeting from 120259499590130093) × 3 ads on existing posts:
     Video 5 饭桌 (sale 11/18), Video 8 我跟你说 (sale 11/19), Video 5 Kaya (sale 11/18)
  B  CBO 1-3-3  「[SG] 儿童长高方程式 | 赢家 CBO 1-3-3 | 1120」 campaign budget RM90
     ad sets Family and Relationships (120259499590130093) / Food and Drink + Milk (120259459018220093) /
     Food & Drink + Milk + Bread (120258189817420093), each with Video 5 饭桌
Audience evidence: adbot-adset-sales-rank-1010 run 44679083254 (60 days, new sale attribution).
Targeting through apply_sg_build_defaults(); optimization / billing / promoted object from the template; url_tags from
config. Names carry 「赢家」, listed in config kpi.cpl_min_spend_overrides (rule 9).
ADBOT_MODE=check (default, read-only) / go (build + read back). Idempotent via state/entities_winners_1120.json.
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
STATE = Path("state") / "entities_winners_1120.json"
POSTS = {  # label -> (ad name, source ad whose post is reused)
    "fanzhuo": ("Video 5：饭桌生活细节场景", "120259499603470093"),
    "gensay": ("Video 8：对话式「我跟你说！」", "120259459021510093"),
    "kaya": ("Video 5：Kaya 面包配 Milo", "120250236477220335"),
}
AUD = {  # label -> (ad set name, template ad set)
    "FR": ("Family and Relationships", "120259499590130093"),
    "FD": ("Interest: Food and Drink + Milk", "120259459018220093"),
    "FDB": ("Food & Drink + Milk + Bread", "120258189817420093"),
}
CAMPAIGNS = {
    "A": {"name": "[SG] 儿童长高方程式 | 赢家 1-1-3 | 1120", "cbo": None,
          "adsets": [("FR", 6000, ["fanzhuo", "gensay", "kaya"])]},
    "B": {"name": "[SG] 儿童长高方程式 | 赢家 CBO 1-3-3 | 1120", "cbo": 9000,
          "adsets": [("FR", None, ["fanzhuo"]), ("FD", None, ["fanzhuo"]), ("FDB", None, ["fanzhuo"])]},
}


def main() -> None:
    log = get_logger()
    s = load_settings()
    m = s.meta
    g = graph_client(s)
    mode = (os.environ.get("ADBOT_MODE") or "check").strip().lower()

    posts = {}
    for lb, (name, src) in POSTS.items():
        a = g.get_object(src, "name,effective_status,creative{effective_object_story_id,object_story_id,title}")
        cr = a.get("creative") or {}
        pid = cr.get("effective_object_story_id") or cr.get("object_story_id")
        if not pid:
            log.error("❌ %s 原广告 %s 读不到 post id，停止，什么都没建。", lb, src)
            sys.exit(1)
        posts[lb] = (name, pid)
        log.info("素材 %s · 原广告 %s %r [%s] → post %s · 标题 %s", lb, src, a.get("name"), a.get("effective_status"),
                 pid, cr.get("title") or "—")
    tpls = {}
    for lb, (aname, tid) in AUD.items():
        tpl = g.get_object(tid, "name,account_id,targeting,promoted_object,optimization_goal,billing_event,bid_strategy")
        if str(tpl.get("account_id")) != ACCT.replace("act_", ""):
            log.error("❌ 模板 %s 不在 SG老户，停止。", tid)
            sys.exit(1)
        t = apply_sg_build_defaults(copy.deepcopy(tpl.get("targeting") or {}))
        ints = [x.get("name") for fs in t.get("flexible_spec") or [] for k in ("interests", "behaviors")
                for x in fs.get(k) or []]
        log.info("受众 %s · 模板 %s %r · %s-%s 岁 · 性别 %s · Adv+ %s · 地区 %s · 兴趣/行为 %s · 排除 %s · 优化 %s",
                 lb, tid, tpl.get("name"), t.get("age_min"), t.get("age_max"), t.get("genders") or "全部",
                 (t.get("targeting_automation") or {}).get("advantage_audience"),
                 (t.get("geo_locations") or {}).get("location_types"), "/".join(ints),
                 [x.get("name") for x in t.get("excluded_custom_audiences") or []] or "—", tpl.get("optimization_goal"))
        tpls[lb] = (aname, tpl, t)
    for ck, c in CAMPAIGNS.items():
        log.info("计划 %s · %r · %s · %s", ck, c["name"], f"CBO RM{c['cbo'] // 100}" if c["cbo"] else "ABO",
                 " | ".join(f"{AUD[a][0]}{' RM' + str(b // 100) if b else ''} → {'/'.join(POSTS[p][0] for p in ps)}"
                            for a, b, ps in c["adsets"]))
    if mode != "go":
        final_summary(log, "预检（只读）：3 个 post、3 个受众模板都读到。没有建任何东西。")
        return

    st = json.loads(STATE.read_text()) if STATE.exists() else {}

    def persist():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    conv = m.conversion_domain_bare or None
    st.setdefault("creatives", {})
    for lb, (name, pid) in posts.items():
        if not st["creatives"].get(lb):
            f = {"name": f"{name} · post · 赢家 1120", "object_story_id": pid}
            if m.url_tags:
                f["url_tags"] = m.url_tags
            st["creatives"][lb] = g.create_adcreative(ACCT, **f)["id"]
            persist()
            time.sleep(0.8)
    for ck, c in CAMPAIGNS.items():
        e = st.setdefault(ck, {"adsets": {}, "ads": {}})
        if not e.get("campaign"):
            f = {"name": c["name"], "objective": m.objective, "buying_type": "AUCTION", "status": "ACTIVE",
                 "special_ad_categories": m.special_ad_categories}
            if c["cbo"]:
                f["daily_budget"] = c["cbo"]
                f["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
            else:
                f["is_adset_budget_sharing_enabled"] = False
            if m.regional_regulated_categories:
                f["regional_regulated_categories"] = m.regional_regulated_categories
            e["campaign"] = g.create_campaign(ACCT, **f)["id"]
            persist()
            time.sleep(1.0)
        for alb, budget, plist in c["adsets"]:
            aname, tpl, t = tpls[alb]
            if not e["adsets"].get(alb):
                f = {"name": aname, "campaign_id": e["campaign"], "status": "ACTIVE",
                     "optimization_goal": tpl.get("optimization_goal"),
                     "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                     "promoted_object": tpl.get("promoted_object") or {}, "targeting": t}
                if budget:
                    f["daily_budget"] = budget
                    f["bid_strategy"] = tpl.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"
                if m.regional_regulated_categories:
                    f["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    f["regional_regulation_identities"] = m.regional_regulation_identities
                e["adsets"][alb] = g.create_adset(ACCT, **f)["id"]
                persist()
                time.sleep(1.0)
            for p in plist:
                key = f"{alb}:{p}"
                if not e["ads"].get(key):
                    e["ads"][key] = g.create_ad(ACCT, name=POSTS[p][0], adset_id=e["adsets"][alb],
                                                creative={"creative_id": st["creatives"][p]}, status="ACTIVE",
                                                conversion_domain=conv)["id"]
                    persist()
                    time.sleep(0.8)

    log.info("═" * 100)
    for ck, c in CAMPAIGNS.items():
        e = st[ck]
        cc = g.get_object(e["campaign"], "name,status,effective_status,daily_budget")
        log.info("读回 %s · campaign %s %r · %s/%s · %s", ck, e["campaign"], cc.get("name"), cc.get("status"),
                 cc.get("effective_status"), f"CBO RM{int(cc.get('daily_budget') or 0) // 100}" if cc.get("daily_budget") else "ABO")
        for alb, asid in e["adsets"].items():
            a_s = g.get_object(asid, "name,status,effective_status,daily_budget")
            log.info("   ad set %s %r · %s/%s · %s", asid, a_s.get("name"), a_s.get("status"), a_s.get("effective_status"),
                     f"RM{int(a_s.get('daily_budget') or 0) // 100}" if a_s.get("daily_budget") else "CBO")
        for key, adid in e["ads"].items():
            ad = g.get_object(adid, "name,status,effective_status")
            log.info("      ad %s %r · %s/%s", adid, ad.get("name"), ad.get("status"), ad.get("effective_status"))
    final_summary(log, f"建好 A {st['A']['campaign']} · B {st['B']['campaign']}")


if __name__ == "__main__":
    main()
