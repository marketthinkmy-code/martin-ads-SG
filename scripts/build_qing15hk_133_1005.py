"""QING 15岁+ on HK as THREE 1-3-3 ABO campaigns (operator correction, 5 Oct: 不是 1-9-9，而是 3 个 1-3-3).

One campaign per audience, each: 3 same-named ad sets × RM50/day (ABO, no budget
sharing) × 1 ad (one video each). Audiences and specs are unchanged from the
first build:
    F&R      — clone of HK ad set 120250013469590335 (Interest: Family and Relationships)
    TEENS    — same base, age 35-60, Adv+ OFF, family_statuses Parents with teenagers /
               preteens read live from the two source ad sets
    BROAD    — same base, no flexible_spec
The first build's single 1-9-9 campaign is deleted by the operator; its 3 creatives
(and page posts) are reused here. Names follow the MY convention:
    [SG] 儿童长高方程式 | <audience> | 15岁以上新片 | 1-3-3
Idempotent via state/entities_qing15hk133_1005.json; Meta throttle exits 75.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

HK = "act_1179668409969241"
OLD_STATE = Path("state") / "entities_qing15hk_1005.json"
STATE_PATH = Path("state") / "entities_qing15hk133_1005.json"
DAILY_MINOR = 5000
TPL_FR = "120250013469590335"
TEEN_SOURCES = ["120250015467160335", "120250696297950093"]
TEEN_PAT = re.compile(r"parents with (teenagers|preteens)", re.IGNORECASE)
SPEC_KINDS = ("interests", "behaviors", "life_events", "family_statuses",
              "industries", "income", "education_statuses", "work_positions")

AUDIENCES: List[Dict[str, str]] = [
    {"key": "fr",    "campaign": "[SG] 儿童长高方程式 | Family and Relationships | 15岁以上新片 | 1-3-3",
     "adset": "Interest: Family and Relationships"},
    {"key": "teens", "campaign": "[SG] 儿童长高方程式 | Parents of Teens 13-17 (35-60) | 15岁以上新片 | 1-3-3",
     "adset": "Parents of Teens 13-17 | 35-60"},
    {"key": "broad", "campaign": "[SG] 儿童长高方程式 | Broad SG 25-65 Adv+ | 15岁以上新片 | 1-3-3",
     "adset": "Broad SG 25-65 | Adv+"},
]
ADS: List[Dict[str, str]] = [
    {"key": "v3", "name": "Video 3：15岁后就不能长高了？", "src_ad": "120249244022910575"},
    {"key": "h2", "name": "Hook 2：上了中学却没有长高？",   "src_ad": "120249244024310575"},
    {"key": "h3", "name": "Hook 3：16岁还长高",            "src_ad": "120249244025140575"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── 0) the first build's single 1-9-9 campaign is deleted BY THE OPERATOR (我会删掉 1-9-9);
    #       only its page posts and creatives are reused here. A creative that no longer
    #       exists is recreated from the post.
    old: Dict[str, Any] = json.loads(OLD_STATE.read_text()) if OLD_STATE.exists() else {}
    st.setdefault("posts", dict(old.get("posts") or {}))
    st.setdefault("creatives", dict(old.get("creatives") or {}))
    for key, cid in list(st["creatives"].items()):
        try:
            g.get_object(cid, "id")
        except GraphError:
            log.info("  creative %s (%s) 已不存在 → 稍后从帖子重建", cid, key)
            st["creatives"].pop(key, None)
    persist()

    # ── base + teen + broad specs (identical to the first build) ──────────────
    tpl = g.get_object(TPL_FR, "name,targeting,promoted_object,optimization_goal,billing_event")
    base: Dict[str, Any] = copy.deepcopy(tpl.get("targeting") or {})
    if not base.get("flexible_spec"):
        log.error("❌ 模板没有 flexible_spec，停止。")
        sys.exit(1)
    ig = base.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        base["instagram_positions"] = list(ig) + ["explore"]
    found: Dict[str, Dict[str, Dict[str, str]]] = {}
    for sid in TEEN_SOURCES:
        try:
            t = g.get_object(sid, "targeting").get("targeting") or {}
        except GraphError:
            continue
        for fs in t.get("flexible_spec") or []:
            for kind in SPEC_KINDS:
                for item in fs.get(kind) or []:
                    if TEEN_PAT.search(item.get("name") or ""):
                        found.setdefault(kind, {})[item["id"]] = {"id": item["id"], "name": item["name"]}
    teen_items = {k: list(v.values()) for k, v in found.items()}
    if not teen_items:
        log.error("❌ 读不到 Parents with teenagers/preteens 标签，停止。")
        sys.exit(1)
    log.info("青少年家长标签: %s", {k: [x["name"] for x in v] for k, v in teen_items.items()})
    t2 = copy.deepcopy(base)
    t2["age_min"], t2["age_max"] = 35, 60
    t2["flexible_spec"] = [teen_items]
    t2["targeting_automation"] = {"advantage_audience": 0}
    t2.pop("age_range", None)
    t3 = copy.deepcopy(base)
    t3.pop("flexible_spec", None)
    specs = {"fr": base, "teens": t2, "broad": t3}

    # ── posts / creatives (reuse; create only if missing) ──────────────────────
    for a in ADS:
        if not st["posts"].get(a["key"]):
            src = g.get_object(a["src_ad"], "name,creative{effective_object_story_id}")
            pid = (src.get("creative") or {}).get("effective_object_story_id")
            if not pid:
                log.error("❌ 源 ad %s 没有帖子 id，停止。", a["src_ad"])
                sys.exit(1)
            st["posts"][a["key"]] = pid
            persist()
        if not st["creatives"].get(a["key"]):
            fields = {"name": a["name"], "object_story_id": st["posts"][a["key"]]}
            if m.url_tags:
                fields["url_tags"] = m.url_tags
            st["creatives"][a["key"]] = g.create_adcreative(HK, **fields)["id"]
            persist()
            time.sleep(1.0)

    # ── 3 campaigns × 3 ad sets × 1 ad ─────────────────────────────────────────
    st.setdefault("campaigns", {})
    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    rows: List[str] = []
    for aud in AUDIENCES:
        k = aud["key"]
        cid = st["campaigns"].get(k)
        if cid:
            try:
                eff = g.get_object(cid, "effective_status").get("effective_status")
            except GraphError:
                eff = "DELETED"
            if eff in ("DELETED", "ARCHIVED"):
                cid = None
        if not cid:
            fields: Dict[str, Any] = {"name": aud["campaign"], "objective": m.objective,
                                      "buying_type": "AUCTION", "status": "PAUSED",
                                      "special_ad_categories": m.special_ad_categories,
                                      "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cid = g.create_campaign(HK, **fields)["id"]
            st["campaigns"][k] = cid
            persist()
            log.info("+ campaign %s %r ABO (PAUSED)", cid, aud["campaign"])
            time.sleep(1.0)
        for a in ADS:
            ak = f"{k}:{a['key']}"
            if not st["adsets"].get(ak):
                fields = {"name": aud["adset"], "campaign_id": cid,
                          "daily_budget": DAILY_MINOR,
                          "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                          "optimization_goal": tpl.get("optimization_goal"),
                          "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                          "promoted_object": tpl.get("promoted_object") or {},
                          "targeting": specs[k], "status": "ACTIVE"}
                if m.regional_regulated_categories:
                    fields["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    fields["regional_regulation_identities"] = m.regional_regulation_identities
                st["adsets"][ak] = g.create_adset(HK, **fields)["id"]
                persist()
                log.info("  + adset %s %r RM%d/日 (%s)", st["adsets"][ak], aud["adset"],
                         DAILY_MINOR // 100, a["key"])
                time.sleep(1.0)
            if not st["ads"].get(ak):
                ad = g.create_ad(HK, name=a["name"], adset_id=st["adsets"][ak],
                                 creative={"creative_id": st["creatives"][a["key"]]},
                                 status="ACTIVE", conversion_domain=conv)
                st["ads"][ak] = ad["id"]
                persist()
                time.sleep(0.8)
            eff = g.get_object(st["ads"][ak], "effective_status").get("effective_status")
            log.info("      ▸ %s %r eff %s", st["ads"][ak], a["name"], eff)
            rows.append(f"{ak}:{eff}")

    final_summary(log, f"QING 15岁+ HK 3×1-3-3 built PAUSED: campaigns {st['campaigns']} · "
                       f"9 adsets × RM{DAILY_MINOR // 100} · {'; '.join(rows)}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
