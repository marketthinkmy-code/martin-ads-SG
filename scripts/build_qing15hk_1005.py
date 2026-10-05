"""QING 15岁+ on the HK account: 1 ABO campaign → 9 ad sets (3 audiences × 3 videos) × RM50, 1 ad each.

Operator (5 Oct): 3 audiences 沒有錯 · ABO · 1 ad set 1 ad RM50 ×9 · ad id 直接用 (three MY ads).
Ad sets carry their audience name (three same-named sets per audience, house style), so sheet
attribution keeps folding by audience; the ad inside tells the videos apart.
    ① Interest: Family and Relationships — cloned from HK ad set 120250013469590335
    ② Parents of Teens 13-17 | 35-60     — base spec of ①, flexible_spec rebuilt from the
         live "Parents with teenagers / preteens" entries found in 120250015467160335
         (HK Parents 3-17 + Engaged) and 120250696297950093 (SG F&R match Business),
         age 35-60; aborts if neither entry can be found
    ③ Broad SG 25-65 | Adv+             — base spec of ①, no flexible_spec
Creatives reuse the MY ads' page posts (shared page → shared engagement), ad names
exactly as the operator wrote them. Campaign PAUSED, ad sets/ads ACTIVE beneath.
Idempotent via state/entities_qing15hk_1005.json; Meta throttle exits 75.
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
STATE_PATH = Path("state") / "entities_qing15hk_1005.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | 15岁+ QING | 1-9-9 ABO"
DAILY_MINOR = 5000
TPL_FR = "120250013469590335"            # Interest: Family and Relationships (HK)
TEEN_SOURCES = ["120250015467160335", "120250696297950093"]
TEEN_PAT = re.compile(r"parents with (teenagers|preteens)", re.IGNORECASE)
SPEC_KINDS = ("interests", "behaviors", "life_events", "family_statuses",
              "industries", "income", "education_statuses", "work_positions")

ADSETS: List[Dict[str, str]] = [
    {"key": "fr",    "name": "Interest: Family and Relationships"},
    {"key": "teens", "name": "Parents of Teens 13-17 | 35-60"},
    {"key": "broad", "name": "Broad SG 25-65 | Adv+"},
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

    # ── base spec from the F&R template ────────────────────────────────────────
    tpl = g.get_object(TPL_FR, "name,targeting,promoted_object,optimization_goal,billing_event")
    base: Dict[str, Any] = copy.deepcopy(tpl.get("targeting") or {})
    log.info("模板 %s %r · geo %s · %s-%s · 性别 %s · Adv+ %s · 排除 %d · flexible_spec %d 组",
             TPL_FR, tpl.get("name"), (base.get("geo_locations") or {}).get("countries"),
             base.get("age_min"), base.get("age_max"), base.get("genders") or "全",
             (base.get("targeting_automation") or {}).get("advantage_audience"),
             len(base.get("excluded_custom_audiences") or []), len(base.get("flexible_spec") or []))
    if not base.get("flexible_spec"):
        log.error("❌ 模板没有兴趣 flexible_spec——不是预期的 F&R 配方，停止。")
        sys.exit(1)
    ig = base.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        base["instagram_positions"] = list(ig) + ["explore"]

    # ── teen spec: live entries from the two source ad sets ────────────────────
    found: Dict[str, Dict[str, Dict[str, str]]] = {}
    for sid in TEEN_SOURCES:
        try:
            t = g.get_object(sid, "targeting").get("targeting") or {}
        except GraphError as exc:
            log.info("  (source %s unreadable: %s)", sid, exc)
            continue
        for fs in t.get("flexible_spec") or []:
            for kind in SPEC_KINDS:
                for item in fs.get(kind) or []:
                    if TEEN_PAT.search(item.get("name") or ""):
                        found.setdefault(kind, {})[item["id"]] = {"id": item["id"], "name": item["name"]}
    teen_items = {k: list(v.values()) for k, v in found.items()}
    log.info("青少年家长标签（live 读到）: %s",
             {k: [x["name"] for x in v] for k, v in teen_items.items()} or "无")
    if not teen_items:
        log.error("❌ 两个来源都读不到 Parents with teenagers/preteens 标签，停止（未建任何东西）。")
        sys.exit(1)

    specs: Dict[str, Dict[str, Any]] = {}
    specs["fr"] = base
    t2 = copy.deepcopy(base)
    t2["age_min"], t2["age_max"] = 35, 60
    t2["flexible_spec"] = [teen_items]
    specs["teens"] = t2
    t3 = copy.deepcopy(base)
    t3.pop("flexible_spec", None)
    specs["broad"] = t3

    # ── source ads → page posts ────────────────────────────────────────────────
    st.setdefault("posts", {})
    for a in ADS:
        if st["posts"].get(a["key"]):
            continue
        src = g.get_object(a["src_ad"], "name,account_id,creative{effective_object_story_id}")
        pid = (src.get("creative") or {}).get("effective_object_story_id")
        log.info("源 ad %s %r (act_%s) → post %s", a["src_ad"], src.get("name"),
                 src.get("account_id"), pid)
        if not pid:
            log.error("❌ 源 ad %s 没有 effective_object_story_id，停止。", a["src_ad"])
            sys.exit(1)
        st["posts"][a["key"]] = pid
        persist()

    # ── campaign (ABO, PAUSED) ─────────────────────────────────────────────────
    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st.pop("campaign_id", None)
    if not st.get("campaign_id"):
        fields: Dict[str, Any] = {"name": CAMPAIGN_NAME, "objective": m.objective,
                                  "buying_type": "AUCTION", "status": "PAUSED",
                                  "special_ad_categories": m.special_ad_categories,
                                  # ABO: Meta requires an explicit answer; the operator wants
                                  # nine independent RM50 budgets, so no 20% sharing.
                                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(HK, **fields)["id"]
        persist()
        log.info("+ campaign %s %r ABO (PAUSED)", st["campaign_id"], CAMPAIGN_NAME)
        time.sleep(1.0)

    # ── creatives (post reuse, one per video, shared by the 3 ad sets) ─────────
    st.setdefault("creatives", {})
    for a in ADS:
        if st["creatives"].get(a["key"]):
            continue
        fields = {"name": a["name"], "object_story_id": st["posts"][a["key"]]}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        st["creatives"][a["key"]] = g.create_adcreative(HK, **fields)["id"]
        persist()
        log.info("  + creative %s ← post %s (%s)", st["creatives"][a["key"]], st["posts"][a["key"]], a["name"])
        time.sleep(1.0)

    # ── 9 ad sets (audience × video), 1 ad each, RM50 ABO ─────────────────────
    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    rows: List[str] = []
    for aset in ADSETS:
        k = aset["key"]
        sp = specs[k]
        for a in ADS:
            ak = f"{k}:{a['key']}"
            if not st["adsets"].get(ak):
                fields = {"name": aset["name"], "campaign_id": st["campaign_id"],
                          "daily_budget": DAILY_MINOR,
                          "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                          "optimization_goal": tpl.get("optimization_goal"),
                          "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                          "promoted_object": tpl.get("promoted_object") or {},
                          "targeting": sp, "status": "ACTIVE"}
                if m.regional_regulated_categories:
                    fields["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    fields["regional_regulation_identities"] = m.regional_regulation_identities
                st["adsets"][ak] = g.create_adset(HK, **fields)["id"]
                persist()
                log.info("+ adset %s %r RM%d/日 · %s-%s · flexible_spec %s · for %s",
                         st["adsets"][ak], aset["name"], DAILY_MINOR // 100,
                         sp.get("age_min"), sp.get("age_max"),
                         "无" if not sp.get("flexible_spec") else
                         [x.get("name") for fs in sp["flexible_spec"] for kind in SPEC_KINDS
                          for x in fs.get(kind) or []][:6], a["key"])
                time.sleep(1.0)
            if not st["ads"].get(ak):
                ad = g.create_ad(HK, name=a["name"], adset_id=st["adsets"][ak],
                                 creative={"creative_id": st["creatives"][a["key"]]},
                                 status="ACTIVE", conversion_domain=conv)
                st["ads"][ak] = ad["id"]
                persist()
                time.sleep(0.8)
            eff = g.get_object(st["ads"][ak], "effective_status").get("effective_status")
            log.info("    ▸ %s %r eff %s", st["ads"][ak], a["name"], eff)
            rows.append(f"{ak}:{eff}")

    final_summary(log, f"QING 15岁+ HK built PAUSED: campaign {st['campaign_id']} · "
                       f"9 adsets × RM{DAILY_MINOR // 100} (1 ad each) · {'; '.join(rows)}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
