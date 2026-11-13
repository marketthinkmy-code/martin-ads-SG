"""11月新片B — 5 MY posts on SG老户, Parents 3-17 + Engaged（女）, 1-5-5 ABO, start 14 Nov 00:00 (operator 13 Nov).

Operator 13 Nov: 「我建议全上啦」, 「1-5-5」 (rule 1), 「B（只投女性），出结构图给我看」, then on the structure chart
「不卡死，你先建，我看一轮 自己手动改，11/14 00:00 开，文案批了」.
  · Account SG老户 act_1024930575770087. One ABO campaign, 5 ad sets (one per video), RM50 each,
    ad set start_time 2026-11-14T00:00:00+08:00, campaign / ad sets / ads ACTIVE so Meta starts them itself.
  · Ads reuse the MY page posts (same Page 341825319024143; MY and SG share the registration page —
    operator 13 Nov 「MY & SG 的报名页是一样的」): creative = object_story_id + config url_tags (SG UTM).
    Copy = the posts' own text, approved by the operator 13 Nov.
  · Targeting cloned from SG老户 ad set 120258845194790093 「Parents 3-17 + Engaged」, genders = women
    (Advantage+ audience left ON as stored — 「不卡死」, so gender is a suggestion), then
    apply_sg_build_defaults() (automatic placements, SG home + frequently in + recent).
  · Campaign name carries 「11月新片B」, added to config kpi.cpl_min_spend_overrides (rule 9).
ADBOT_MODE=check (default): read-only — template targeting, the 5 posts as used by MY's ads, Meta's audience
estimate; nothing written. ADBOT_MODE=go: build, read back. Idempotent via state/entities_nov14_b.json.
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
START = "2026-11-14T00:00:00+0800"
DAILY_MINOR = 5000
TEMPLATE = "120258845194790093"            # SG老户 「Parents 3-17 + Engaged」
CAMPAIGN = "[SG] 儿童长高方程式 | Parents 3-17 + Engaged（女） | 11月新片B 5支 | 1-5-5"
ADSET = "Parents 3-17 + Engaged（女）"
STATE = Path("state") / "entities_nov14_b.json"
# (ad name, page post id, MY ad that already uses the post — read only, to prove the post id)
VIDEOS = [
    ("Hook 1：吃完就上廁所？！", "341825319024143_122203372238485585", "120249864328410575"),
    ("Video 7：14歲了，還有機會長高嗎", "341825319024143_122203372298485585", "120249864329070575"),
    ("Video 8：鼻塞的孩子长不高", "341825319024143_122203372424485585", "120249864330010575"),
    ("Video 9：鼻子不通的孩子，长不高", "341825319024143_122203372484485585", "120249864330460575"),
    ("Video 10：不是吃不够，是吸收不到", "341825319024143_122203372592485585", "120249864331280575"),
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    m = s.meta
    g = graph_client(s)
    mode = (os.environ.get("ADBOT_MODE") or "check").strip().lower()
    log.info("SG老户 %s · 模式 %s · 开始时间 %s · campaign %r", ACCT, mode, START, CAMPAIGN)

    for name, pid, my_ad in VIDEOS:
        a = g.get_object(my_ad, "name,account_id,effective_status,creative{effective_object_story_id,object_story_id}")
        cr = a.get("creative") or {}
        got = cr.get("effective_object_story_id") or cr.get("object_story_id")
        ok = got == pid
        log.info("  %s · post %s · MY 广告 %s %r（%s）用的 post %s · 对得上 %s", name, pid, my_ad, a.get("name"),
                 a.get("effective_status"), got, "✓" if ok else "✗")
        if not ok:
            log.error("❌ post id 对不上，停止，什么都没建。")
            sys.exit(1)

    tpl = g.get_object(TEMPLATE, "name,account_id,targeting,promoted_object,optimization_goal,billing_event,bid_strategy")
    if str(tpl.get("account_id")) != ACCT.replace("act_", ""):
        log.error("❌ 模板 %s 不在 SG老户，停止。", TEMPLATE)
        sys.exit(1)
    t = apply_sg_build_defaults(copy.deepcopy(tpl.get("targeting") or {}))
    t["genders"] = [2]                     # women — suggestion while Advantage+ audience stays on (「不卡死」)
    fs = t.get("flexible_spec") or []
    names = [x.get("name") for f in fs for kind in ("interests", "behaviors", "family_statuses") for x in f.get(kind) or []]
    log.info("  模板 %s %r · %s-%s 岁 · 性别 %s · Adv+ 受众 %s · 语言 %s · 地区 %s · 定向：%s · 排除 %s · 版位 自动",
             TEMPLATE, tpl.get("name"), t.get("age_min"), t.get("age_max"), t.get("genders"),
             (t.get("targeting_automation") or {}).get("advantage_audience"), t.get("locales"),
             t.get("geo_locations"), " / ".join(names), [x.get("name") for x in t.get("excluded_custom_audiences") or []])
    log.info("  出价 %s · 优化 %s · 计费 %s · %s", tpl.get("bid_strategy"), tpl.get("optimization_goal"),
             tpl.get("billing_event"), tpl.get("promoted_object"))
    try:
        est = g._request("GET", f"{ACCT}/delivery_estimate", params={
            "targeting_spec": json.dumps(t), "optimization_goal": tpl.get("optimization_goal") or "OFFSITE_CONVERSIONS",
            "promoted_object": json.dumps(tpl.get("promoted_object") or {})})
        for e in est.get("data", []):
            log.info("  Meta 估计受众人数：%s – %s", e.get("estimate_mau_lower_bound"), e.get("estimate_mau_upper_bound"))
    except Exception as exc:  # noqa: BLE001
        log.info("  受众人数读不到：%s", str(exc)[:200])
    if mode != "go":
        final_summary(log, "预检（只读）：5 个 post id 对得上 MY 的广告；模板读到。没有建任何东西。")
        return

    st = json.loads(STATE.read_text()) if STATE.exists() else {}

    def persist():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    if not st.get("campaign_id"):
        for c in g._get_all(f"{ACCT}/campaigns", {"fields": "id,name,effective_status", "limit": 200}):
            if c.get("name") == CAMPAIGN and c.get("effective_status") not in ("DELETED", "ARCHIVED"):
                st["campaign_id"] = c["id"]
                if g._get_all(f"{c['id']}/adsets", {"fields": "id", "limit": 50}):
                    log.error("❌ campaign %s 里已经有 ad set，停止，免得重复。", c["id"])
                    sys.exit(1)
                persist()
                log.info("  沿用上次建了一半的 campaign %s", c["id"])
                break
    if not st.get("campaign_id"):
        f = {"name": CAMPAIGN, "objective": m.objective, "buying_type": "AUCTION", "status": "ACTIVE",
             "special_ad_categories": m.special_ad_categories, "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            f["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(ACCT, **f)["id"]
        persist()
        log.info("+ campaign %s ABO", st["campaign_id"])
        time.sleep(1.0)
    for d in ("creatives", "adsets", "ads"):
        st.setdefault(d, {})
    conv = m.conversion_domain_bare or None
    for i, (name, pid, _my) in enumerate(VIDEOS, 1):
        k = str(i)
        if not st["creatives"].get(k):
            f = {"name": f"{name} · post", "object_story_id": pid}
            if m.url_tags:
                f["url_tags"] = m.url_tags
            st["creatives"][k] = g.create_adcreative(ACCT, **f)["id"]
            persist()
            time.sleep(0.8)
        if not st["adsets"].get(k):
            f = {"name": ADSET, "campaign_id": st["campaign_id"], "daily_budget": DAILY_MINOR, "status": "ACTIVE",
                 "start_time": START, "optimization_goal": tpl.get("optimization_goal"),
                 "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                 "promoted_object": tpl.get("promoted_object") or {}, "targeting": t,
                 "bid_strategy": tpl.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"}
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
    log.info("campaign %s %r · %s / %s", st["campaign_id"], c.get("name"), c.get("status"), c.get("effective_status"))
    rows = []
    for i, (name, pid, _my) in enumerate(VIDEOS, 1):
        k = str(i)
        a_s = g.get_object(st["adsets"][k], "name,status,effective_status,daily_budget,start_time,targeting")
        ad = g.get_object(st["ads"][k], "name,status,effective_status,creative{effective_object_story_id,url_tags}")
        tt = a_s.get("targeting") or {}
        cr = ad.get("creative") or {}
        log.info("  %s · ad set %s RM%d %s/%s 开始 %s · 性别 %s · Adv+ %s · 地区 %s · 版位 %s · ad %s %s/%s · post %s %s · UTM %s",
                 name, st["adsets"][k], int(a_s.get("daily_budget") or 0) // 100, a_s.get("status"),
                 a_s.get("effective_status"), a_s.get("start_time"), tt.get("genders"),
                 (tt.get("targeting_automation") or {}).get("advantage_audience"),
                 (tt.get("geo_locations") or {}).get("location_types"),
                 "自动" if not tt.get("publisher_platforms") else tt.get("publisher_platforms"), st["ads"][k],
                 ad.get("status"), ad.get("effective_status"), cr.get("effective_object_story_id"),
                 "✓" if cr.get("effective_object_story_id") == pid else "✗", "有" if cr.get("url_tags") else "没有")
        rows.append(f"{name} ad {st['ads'][k]}")
    final_summary(log, f"建好（SG老户，11/14 00:00 开始）campaign {st['campaign_id']} · " + " | ".join(rows))


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
