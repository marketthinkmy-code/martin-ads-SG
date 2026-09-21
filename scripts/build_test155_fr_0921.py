"""新片 5 支测试 (21 Sep): ONE campaign · ONE ad set RM100/day · FIVE ads · 7 days hands-off.

Operator's spec, verbatim:
    新 campaign「[SG] 儿童长高方程式 | Family and Relationships | 新片 5 支测试 | 1-1-5」
    ABO · ad set 预算 RM100/day · ad set 名「Interest: Family and Relationships」
    定向从 F&R 赢家 ad set 克隆（120257269400410093 · 16 单 · Adv+OFF 锁死 · 18-65）
    买家名单排除（settings 的 excluded_custom_audiences）· 马来西亚声明照抄（regional fields）
    5 支 ad 用已 mint 好的 creative（New Wave 0914 的），不重新上传：
        Hook 1 今晚回家 (10,000 版) · Hook 4 保健品叫你丢掉 · Hook 7 算给你看 ·
        Hook 3 倒掉牛奶 · Hook 6 没有人会告诉你
    7 天不动 —— the five names go into config cpl_hold (committed separately) so the daily
    CPL cut and zero-reg kill cannot touch the test until 9/28.

Also pauses any stray LIVE copy of these five names outside the new campaign (the two
RM40 F&R chains), so the test is the only place they run. Idempotent via
state/entities_test155_fr_0921.json; audit within.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

sys.path.insert(0, str(Path(__file__).parent))
from build_new_wave_0914 import (  # noqa: E402
    STATE_PATH as NW_STATE, clone_targeting, verify_expansion)

STATE_PATH = Path("state") / "entities_test155_fr_0921.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Family and Relationships | 新片 5 支测试 | 1-1-5"
ADSET_NAME = "Interest: Family and Relationships"
FR_SOURCE = "120257269400410093"
DAILY_MINOR = 10000                     # RM100/day on the ad set (ABO)

# key → (ad name, creative source): "fixed" uses the pinned 10,000-version creative id;
# "state" reads the minted creative from the New Wave state file.
ADS: List[Dict[str, str]] = [
    {"key": "hook1", "ad_name": "Hook 1：今晚回家检查三件事", "creative_id": "2605128693280832"},
    {"key": "nh4", "ad_name": "Hook 4：保健品叫你丢掉"},
    {"key": "xh7", "ad_name": "Hook 7：算给你看"},
    {"key": "xh3", "ad_name": "Hook 3：倒掉牛奶"},
    {"key": "xh6", "ad_name": "Hook 6：没有人会告诉你"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    nw = json.loads(NW_STATE.read_text())
    for a in ADS:
        if not a.get("creative_id"):
            a["creative_id"] = nw["creatives"][a["key"]]["creative_id"]
        g.get_object(a["creative_id"], "id")        # must still exist
    log.info("5 creatives verified: %s", ", ".join(a["creative_id"] for a in ADS))

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    spec = clone_targeting(g, FR_SOURCE, s)
    spec["targeting_automation"] = {"advantage_audience": 0}   # 赢家定向锁死，防 Meta 偷改
    log.info("Targeting cloned from %s: ages %s-%s · Adv+ OFF · %d flexible_spec · "
             "%d excluded audiences", FR_SOURCE, spec.get("age_min"), spec.get("age_max"),
             len(spec.get("flexible_spec") or []),
             len(spec.get("excluded_custom_audiences") or []))

    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st = {}
    if not st.get("campaign_id"):
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective,
                  "buying_type": "AUCTION", "status": "ACTIVE",
                  "special_ad_categories": m.special_ad_categories,
                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(acct, **fields)["id"]
        persist()
        log.info("+ campaign %s %r (ACTIVE)", st["campaign_id"], CAMPAIGN_NAME)
        time.sleep(1.0)

    if not st.get("adset_id"):
        fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"],
                  "optimization_goal": m.optimization_goal,
                  "billing_event": "IMPRESSIONS", "promoted_object": m.promoted_object,
                  "targeting": spec, "status": "ACTIVE",
                  "daily_budget": DAILY_MINOR,
                  "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            fields["regional_regulation_identities"] = m.regional_regulation_identities
        st["adset_id"] = g.create_adset(acct, **fields)["id"]
        persist()
        verify_expansion(g, st["adset_id"], spec, 0, log)
        log.info("+ adset %s %r RM100/day (ACTIVE)", st["adset_id"], ADSET_NAME)
        time.sleep(1.0)

    st.setdefault("ads", {})
    for a in ADS:
        if st["ads"].get(a["key"]):
            continue
        ad = g.create_ad(acct, name=a["ad_name"], adset_id=st["adset_id"],
                         creative={"creative_id": a["creative_id"]},
                         status="ACTIVE", conversion_domain=conv)
        st["ads"][a["key"]] = ad["id"]
        persist()
        log.info("+ ad %s %r", ad["id"], a["ad_name"])
        time.sleep(1.0)

    # ── the test is now the ONLY place these five run: pause stray live copies ──
    all_ads = g._get_all(f"{acct}/ads",
                         {"fields": "id,name,status,effective_status,adset_id,campaign_id",
                          "limit": 500})
    test_ids = set(st["ads"].values())
    keys = {cpa.ad_key(a["ad_name"]) for a in ADS}
    strays = [x for x in all_ads
              if x["id"] not in test_ids and cpa.ad_key(x.get("name") or "") in keys
              and x.get("effective_status") == "ACTIVE"]
    for x in strays:
        g.update_status(x["id"], "PAUSED")
        x["status"] = "PAUSED"
        others = [y for y in all_ads if y.get("adset_id") == x.get("adset_id")
                  and y["id"] != x["id"] and y.get("status") == "ACTIVE"]
        if x.get("adset_id") and not others:
            g.update_status(x["adset_id"], "PAUSED")
        log.info("stray copy paused: ad %s (adset %s)", x["id"], x.get("adset_id"))
        time.sleep(1.0)

    rows = []
    for a in ADS:
        eff = g.get_object(st["ads"][a["key"]], "effective_status").get("effective_status")
        rows.append(f"{a['key']}:{eff}")
    st["strays_paused"] = [x["id"] for x in strays]
    persist()
    final_summary(log, f"新片 5 支测试 live: campaign {st['campaign_id']} · adset "
                       f"{st['adset_id']} RM100/day · 5 ads ({'; '.join(rows)}) · "
                       f"{len(strays)} stray live copies paused. 7-day hands-off runs on "
                       f"the cpl_hold entries committed with this build.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
