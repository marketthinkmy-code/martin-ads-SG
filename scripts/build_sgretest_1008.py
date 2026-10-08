"""新片5支重测 on the old SG account: 3 audiences × (1 CBO RM100 campaign → 1 ad set → 5 ads).

Operator (8 Oct): 照建 (CBO 1-1-5, RM100/day, F&R + Parents 3-17 + Engaged) and
等下建完了，再建 Food & Milk 的. The five ads reuse existing page posts:
    Video 3 / Hook 2 / Hook 3        ← posts recorded in state/entities_qing15hk133_1005.json
    Video 1 線下見面 / Video 2 17cm    ← effective_object_story_id of the HK creatives in
                                         state/entities_offline_1006.json
Ad-set targeting is cloned from the lineage templates (F&R and Parents 3-17 + Engaged
from HK, Food and Drink + Milk from this account's New Wave set). All PAUSED.
Idempotent via state/entities_sgretest_1008.json; Meta throttle exits 75.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_sgretest_1008.json"
QING_STATE = Path("state") / "entities_qing15hk133_1005.json"
OFFLINE_STATE = Path("state") / "entities_offline_1006.json"
CBO_MINOR = 10000
THEME = "新片5支重测"

CAMPAIGNS: List[Dict[str, str]] = [
    {"key": "fr", "tpl": "120250013469590335",
     "name": f"[SG] 儿童长高方程式 | Family and Relationships | {THEME} | 1-1-5",
     "adset": "Interest: Family and Relationships"},
    {"key": "p317", "tpl": "120250015467160335",
     "name": f"[SG] 儿童长高方程式 | Parents 3-17 + Engaged | {THEME} | 1-1-5",
     "adset": "Parents 3-17 + Engaged"},
    {"key": "milk", "tpl": "120258340110730093",
     "name": f"[SG] 儿童长高方程式 | Food and Drink + Milk | {THEME} | 1-1-5",
     "adset": "Interest: Food and Drink + Milk"},
]
ADS: List[Dict[str, str]] = [
    {"key": "v3", "name": "Video 3：15岁后就不能长高了？", "src": "qing:v3"},
    {"key": "h2", "name": "Hook 2：上了中学却没有长高？",   "src": "qing:h2"},
    {"key": "h3", "name": "Hook 3：16岁还长高",            "src": "qing:h3"},
    {"key": "v1", "name": "Video 1：KL&SG 線下見面",         "src": "offline:v1"},
    {"key": "v2", "name": "Video 2：長高了17cm",            "src": "offline:v2"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    acct = m.account_path                      # old SG account
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── resolve the five page posts ─────────────────────────────────────────────
    st.setdefault("posts", {})
    qing = json.loads(QING_STATE.read_text()) if QING_STATE.exists() else {}
    offl = json.loads(OFFLINE_STATE.read_text()) if OFFLINE_STATE.exists() else {}
    for a in ADS:
        if st["posts"].get(a["key"]):
            continue
        src, k = a["src"].split(":")
        if src == "qing":
            pid = (qing.get("posts") or {}).get(k)
        else:
            cid = (offl.get("creatives") or {}).get(k)
            pid = g.get_object(cid, "effective_object_story_id").get("effective_object_story_id") if cid else None
        if not pid:
            log.error("❌ %r 拿不到帖子 id（%s）——停止，未建任何东西。", a["name"], a["src"])
            sys.exit(1)
        st["posts"][a["key"]] = pid
        log.info("帖子 %-28s → %s", a["name"][:28], pid)
    persist()

    # ── creatives on this account (post reuse) ─────────────────────────────────
    st.setdefault("creatives", {})
    for a in ADS:
        if st["creatives"].get(a["key"]):
            continue
        fields = {"name": a["name"], "object_story_id": st["posts"][a["key"]]}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        st["creatives"][a["key"]] = g.create_adcreative(acct, **fields)["id"]
        persist()
        log.info("  + creative %s ← %s", st["creatives"][a["key"]], a["name"])
        time.sleep(0.8)

    st.setdefault("campaigns", {})
    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    rows: List[str] = []
    for c in CAMPAIGNS:
        ck = c["key"]
        tpl = g.get_object(c["tpl"], "name,targeting,promoted_object,optimization_goal,billing_event")
        t = copy.deepcopy(tpl.get("targeting") or {})
        if not t.get("flexible_spec"):
            log.error("❌ 模板 %s 没有兴趣配方，停止。", c["tpl"])
            sys.exit(1)
        ig = t.get("instagram_positions")
        if ig and "explore_home" in ig and "explore" not in ig:
            t["instagram_positions"] = list(ig) + ["explore"]
        ints = [x.get("name") for fs in t["flexible_spec"] for kind in
                ("interests", "behaviors", "family_statuses") for x in fs.get(kind) or []]
        log.info("═══ %s · 模板 %s %r · %s-%s · Adv+ %s · 排除 %d · %s", ck, c["tpl"], tpl.get("name"),
                 t.get("age_min"), t.get("age_max"),
                 (t.get("targeting_automation") or {}).get("advantage_audience"),
                 len(t.get("excluded_custom_audiences") or []), "/".join(ints[:5]))

        cid = st["campaigns"].get(ck)
        if cid:
            try:
                eff = g.get_object(cid, "effective_status").get("effective_status")
            except GraphError:
                eff = "DELETED"
            if eff in ("DELETED", "ARCHIVED"):
                cid = None
        if not cid:
            fields: Dict[str, Any] = {"name": c["name"], "objective": m.objective,
                                      "buying_type": "AUCTION", "status": "PAUSED",
                                      "special_ad_categories": m.special_ad_categories,
                                      "daily_budget": CBO_MINOR,
                                      "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cid = g.create_campaign(acct, **fields)["id"]
            st["campaigns"][ck] = cid
            persist()
            log.info("+ campaign %s %r CBO RM%d/day (PAUSED)", cid, c["name"], CBO_MINOR // 100)
            time.sleep(1.0)
        if not st["adsets"].get(ck):
            fields = {"name": c["adset"], "campaign_id": cid,
                      "optimization_goal": tpl.get("optimization_goal"),
                      "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                      "promoted_object": tpl.get("promoted_object") or {},
                      "targeting": t, "status": "ACTIVE"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            st["adsets"][ck] = g.create_adset(acct, **fields)["id"]
            persist()
            log.info("+ adset %s %r", st["adsets"][ck], c["adset"])
            time.sleep(1.0)
        for a in ADS:
            ak = f"{ck}:{a['key']}"
            if not st["ads"].get(ak):
                ad = g.create_ad(acct, name=a["name"], adset_id=st["adsets"][ck],
                                 creative={"creative_id": st["creatives"][a["key"]]},
                                 status="ACTIVE", conversion_domain=conv)
                st["ads"][ak] = ad["id"]
                persist()
                time.sleep(0.8)
            eff = g.get_object(st["ads"][ak], "effective_status").get("effective_status")
            log.info("    ▸ %s %r eff %s", st["ads"][ak], a["name"], eff)
            rows.append(f"{ak}:{eff}")

    final_summary(log, f"{THEME} built PAUSED on {acct}: campaigns {st['campaigns']} · "
                       f"CBO RM{CBO_MINOR // 100}/day each · {len(rows)} ads")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
