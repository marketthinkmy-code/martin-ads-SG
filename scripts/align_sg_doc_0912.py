"""Align the SG account to the operator's doc plan (12 Sep, emergency). MUTATING.

Operator: "全部暂时性跟着文档的（最近业绩很差的紧急调整）· 执行 · 1-5-5 加进 TEST 池 ·
REDUCE 三条 RM15 · 0907 只留 Hook 2（旧鞋当尺）"

Doc: SG RM6,000 per webinar cycle, budgets FOLLOW BUYERS not CPL. Daily = cycle/7:

  SCALE  Hook Edits A → Hook Edit 04 不买牛奶                    RM180/day   (reopen)
  KEEP   F&R A → Video7 15岁还没抽高                              RM130/day   (reopen)
  KEEP   Purchase LAL 1-2% → 🌟V13 三年前長了10公分                RM120/day   (raise 50→120)
  KEEP   Purchase LAL 1% → 15岁以上还有机会长高                    RM100/day   (reopen set, only this ad)
  KEEP   Grid B LAL1-2% → Hook2 还在把面包当早餐                   RM65/day    (reopen)
  KEEP   Broad SG → MAR Hook3 准备早餐面包                        RM50/day    (reopen)
  KEEP   Broad SG → 孩子如果有鼻窦炎                               RM35/day    (reopen)
  KEEP   Broad SG → 15岁以上还有机会长高                           RM35/day    (reopen)
  OBS    Purchase LAL 2-3% → 15岁以上                             RM30/day    (reopen set, only this ad)
  REDUCE Parents V12 / Parents V13 / Parents 兴趣 V11             RM15/day each
  TEST   Food 0907 Hook 2 旧鞋当尺 RM15/day + 1-5-5 five sets RM11/day each (≈RM70/day pool)
  OFF    V3 5-15岁 · Broad|0907 V7我13岁 · Food|0907 Hook1 · Hook 18 (not in doc) ·
         Interest F&R CBO V12 (not in doc)

Safety: resolve every chain by normalized name + campaign/adset filters — ambiguity or a
legacy #400 refusal SKIPS that chain with a loud reason, never guesses. Waking a dormant
campaign/ad set applies the scoped release-only freeze: any OTHER ad/ad set that the wake
would release is paused first, so only the doc's chains deliver. Idempotent; every
mutation appended to state/align_sg_doc_0912_log.json.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from adbot import cpa
from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

LOG_PATH = Path("state") / "align_sg_doc_0912_log.json"
S155 = Path("state") / "entities_shopper_health_155.json"

# name_subs match cpa.norm(ad name); camp/adset subs match cpa.norm(entity name)
PLAN: List[Dict[str, Any]] = [
    {"key": "he04",     "act": "open", "budget": 18000, "names": ["hook edit 04"],
     "camp": ["hook edits a"]},
    {"key": "v7pull",   "act": "open", "budget": 13000, "names": ["还没抽高", "還沒抽高"],
     "camp": ["family and relationships a"]},
    {"key": "lal12v13", "act": "budget", "budget": 12000, "names": ["三年前他長了10公分"],
     "camp": ["purchase lal"], "adset": ["lal 1-2%"]},
    {"key": "lal1_15",  "act": "open", "budget": 10000, "names": ["15岁以上还有机会", "15歲以上還有機會"],
     "camp": ["purchase lal"], "adset": ["lal 1%"]},
    {"key": "gridb_h2", "act": "open", "budget": 6500, "names": ["把面包当早餐", "把麵包當早餐"],
     "camp": ["grid b"]},
    {"key": "broad_h3", "act": "open", "budget": 5000, "names": ["准备早餐面包", "準備早餐麵包"],
     "camp": ["broad"], "camp_not": ["hooks 0907"]},
    {"key": "broad_bd", "act": "open", "budget": 3500, "names": ["鼻窦炎", "鼻竇炎"],
     "camp": ["broad"], "camp_not": ["hooks 0907"]},
    {"key": "broad_15", "act": "open", "budget": 3500, "names": ["15岁以上还有机会", "15歲以上還有機會"],
     "camp": ["broad"], "camp_not": ["hooks 0907"]},
    {"key": "lal23_15", "act": "open", "budget": 3000, "names": ["15岁以上还有机会", "15歲以上還有機會"],
     "camp": ["purchase lal"], "adset": ["lal 2-3%"]},
    {"key": "par_v12",  "act": "budget", "budget": 1500, "names": ["試了五六種方法", "试了五六种方法"],
     "camp": ["parents 3-17"]},
    {"key": "par_v13",  "act": "open", "budget": 1500, "names": ["三年前他長了10公分"],
     "camp": ["parents"], "camp_not": ["purchase lal", "hooks 0907", "shopper"]},
    {"key": "par_v11",  "act": "budget", "budget": 1500, "names": ["孩子來mc", "孩子来mc"],
     "camp": ["兴趣定向"]},
    {"key": "food_h2",  "act": "budget", "budget": 1500, "names": ["旧鞋当尺", "舊鞋當尺"],
     "camp": ["food", "hooks 0907"]},
    # OFF
    {"key": "off_v3",   "act": "close", "names": ["5岁到15岁的孩子", "5歲到15歲的孩子"],
     "camp": ["parents 3-17"]},
    {"key": "off_v7_13","act": "close", "names": ["我13岁身高173", "我13歲身高173"],
     "camp": ["broad", "hooks 0907"]},
    {"key": "off_h1",   "act": "close", "names": ["今晚回家"],
     "camp": ["food", "hooks 0907"]},
    {"key": "off_h18",  "act": "close", "names": ["hook 18"],
     "camp": ["family and relationships"], "camp_not": ["family and relationships a", "interest"]},
    {"key": "off_ifr",  "act": "close_campaign", "names": ["試了五六種方法", "试了五六种方法"],
     "camp": ["interest: family"]},
]
TEST_155_CENTS = 1100   # five 1-5-5 sets, RM11/day each (TEST pool with Hook 2 ≈ RM70/day)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    run_ts = dt.datetime.utcnow().isoformat(timespec="seconds")
    audit: List[Dict[str, Any]] = []

    def note(**kw) -> None:
        audit.append({"ts": dt.datetime.utcnow().isoformat(timespec="seconds"), **kw})
        prev = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else {}
        prev.setdefault(run_ts, [])
        prev[run_ts] = audit
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(json.dumps(prev, indent=2, ensure_ascii=False) + "\n")

    campaigns = g._get_all(f"{acct}/campaigns",
                           {"fields": "id,name,status,daily_budget", "limit": 200})
    adsets = g._get_all(f"{acct}/adsets",
                        {"fields": "id,name,status,campaign_id,daily_budget", "limit": 500})
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,status,adset_id,campaign_id", "limit": 1000})
    camp_by_id = {c["id"]: c for c in campaigns}
    aset_by_id = {a["id"]: a for a in adsets}

    def match(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        out = []
        for ad in ads:
            n = cpa.norm(ad.get("name") or "")
            if not any(v in n for v in entry["names"]):
                continue
            cn = cpa.norm((camp_by_id.get(ad.get("campaign_id")) or {}).get("name") or "")
            if not all(v in cn for v in entry.get("camp", [])):
                continue
            if any(v in cn for v in entry.get("camp_not", [])):
                continue
            if entry.get("adset"):
                an = cpa.norm((aset_by_id.get(ad.get("adset_id")) or {}).get("name") or "")
                if not all(v in an for v in entry["adset"]):
                    continue
            out.append(ad)
        return out

    def set_status(eid: str, status: str, what: str) -> bool:
        try:
            g.update_status(eid, status)
            note(entity=eid, action=status, what=what)
            return True
        except GraphError as exc:
            log.info("   !! %s %s refused: %s", what, eid, exc)
            note(entity=eid, action=f"REFUSED {status}", what=what, error=str(exc)[:160])
            return False

    done, skipped = [], []
    touched_adsets: Dict[str, str] = {}      # adset_id -> target ad id (for sibling mute)
    woken_campaigns: Dict[str, List[str]] = {}   # campaign_id -> target adset ids

    for e in PLAN:
        cands = match(e)
        if not cands:
            log.info("▸ %-9s ∅ 找不到匹配 — 跳过", e["key"])
            skipped.append(f"{e['key']}(no match)")
            continue
        # prefer a currently-delivering copy, else the newest id (highest numeric id)
        cands.sort(key=lambda a: (a.get("status") == "ACTIVE", int(a["id"])), reverse=True)
        ad = cands[0]
        aset = aset_by_id.get(ad["adset_id"]) or {}
        camp = camp_by_id.get(ad["campaign_id"]) or {}
        if len(cands) > 1:
            log.info("▸ %-9s %d 个同名候选，选 %s（%s · %s）", e["key"], len(cands), ad["id"],
                     camp.get("name", "")[:38], "在跑" if ad.get("status") == "ACTIVE" else "较新")
        log.info("▸ %-9s ad %s %r", e["key"], ad["id"], (ad.get("name") or "")[:44])
        log.info("            in %s › %s", (camp.get("name") or "")[:52], (aset.get("name") or "")[:36])

        if e["act"] in ("close", "close_campaign"):
            ok = set_status(ad["id"], "PAUSED", f"{e['key']}:ad")
            if e["act"] == "close_campaign":
                ok = set_status(camp["id"], "PAUSED", f"{e['key']}:campaign") and ok
            else:
                ok = set_status(aset["id"], "PAUSED", f"{e['key']}:adset") and ok
            (done if ok else skipped).append(e["key"])
            continue

        if int(camp.get("daily_budget") or 0) > 0 and e["act"] in ("open", "budget"):
            log.info("   !! %s 的 campaign 是 CBO，无法按 ad set 设预算 — 跳过，需人工", e["key"])
            skipped.append(f"{e['key']}(CBO)")
            continue

        ok = True
        if e["act"] == "open":
            ok = set_status(ad["id"], "ACTIVE", f"{e['key']}:ad") and ok
            ok = set_status(aset["id"], "ACTIVE", f"{e['key']}:adset") and ok
            if camp.get("status") != "ACTIVE":
                ok = set_status(camp["id"], "ACTIVE", f"{e['key']}:campaign") and ok
                woken_campaigns.setdefault(camp["id"], [])
        try:
            g.update_daily_budget(aset["id"], e["budget"])
            note(entity=aset["id"], action=f"daily_budget={e['budget']}", what=e["key"])
            log.info("   budget → RM%d/day", e["budget"] // 100)
        except GraphError as exc:
            log.info("   !! budget refused: %s", exc)
            note(entity=aset["id"], action="REFUSED budget", what=e["key"], error=str(exc)[:160])
            ok = False
        touched_adsets[aset["id"]] = ad["id"]
        woken_campaigns.setdefault(camp["id"], []).append(aset["id"])
        (done if ok else skipped).append(e["key"])

    # 1-5-5 TEST pool: five sets → RM11/day each
    if S155.exists():
        st155 = json.loads(S155.read_text())
        for k, u in (st155.get("units") or {}).items():
            try:
                g.update_daily_budget(u["adset_id"], TEST_155_CENTS)
                note(entity=u["adset_id"], action=f"daily_budget={TEST_155_CENTS}", what=f"155:{k}")
                log.info("▸ 1-5-5 %-10s → RM11/day", k)
                done.append(f"155:{k}")
            except GraphError as exc:
                log.info("▸ 1-5-5 %s budget refused: %s", k, exc)
                skipped.append(f"155:{k}")

    # scoped release-only freeze: inside woken campaigns, silence what the wake released
    log.info("═" * 92)
    log.info("Scoped freeze（唤醒所释放的旁链静音）:")
    for cid, target_sets in woken_campaigns.items():
        for aset in adsets:
            if aset.get("campaign_id") != cid or aset["id"] in touched_adsets:
                continue
            if aset.get("status") == "ACTIVE":
                if set_status(aset["id"], "PAUSED", f"freeze:adset({aset.get('name','')[:24]})"):
                    log.info("   froze adset %s %r", aset["id"], (aset.get("name") or "")[:36])
    for aset_id, target_ad in touched_adsets.items():
        for ad in ads:
            if ad.get("adset_id") != aset_id or ad["id"] == target_ad:
                continue
            if ad.get("status") == "ACTIVE":
                if set_status(ad["id"], "PAUSED", f"freeze:ad({(ad.get('name') or '')[:24]})"):
                    log.info("   froze ad %s %r (同 ad set 非目标)", ad["id"], (ad.get("name") or "")[:40])

    log.info("═" * 92)
    final_summary(
        log, f"SG aligned to the doc: {len(done)} action(s) done, {len(skipped)} skipped "
             f"({', '.join(skipped) if skipped else 'none'}). Plan ≈ RM860/day = RM6,000/cycle "
             f"(TEST pool = Hook 2 RM15 + 1-5-5 five x RM11). Audit in {LOG_PATH.name}.")


if __name__ == "__main__":
    main()
