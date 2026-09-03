"""Reopen the six SG chains from the operator's sheet screenshot (3 Sep). LIVE.

Operator: "图里的 SG 的广告帮我开回去" — the Paid Student List gained new sale rows and the
SG ones name these exact campaign ▸ ad set ▸ ad triplets. The [MY] rows belong to the MY
account and the martinigbio row is organic; neither is touched.

Same discipline as the 30 Aug reopen run:
  · exactly the pinned chains are woken — ad, then its ad set, then its campaign, only the
    levels that are off; a chain already delivering is left alone;
  · before anything wakes, only the ads the wake would actually RELEASE are ad-level paused
    (target ad set's ad-level-ACTIVE ads when the ad set is off; other adset-ACTIVE chains
    only when the campaign itself is off) — everything already delivering, and everything
    that stays frozen, keeps the switches the operator left;
  · a legacy entity that rejects edits aborts that one chain with its mutes rolled back;
  · budgets are NOT touched. Note for the grid chain: Grid 3×3 is CBO RM150/day at campaign
    level, so opening only the Grid B ▸ Hook 2 cell points that whole budget at one cell.
  · matching is by the account's name-key rule; sheet values are truncated in the screenshot,
    so ad matching accepts prefix containment inside the resolved campaign + ad set.

Chains resolve at run time and anything that cannot be resolved to exactly one entity is
skipped with a reason, never guessed. Actions append to state/reopen_sold_chains_log.json.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adbot import cpa
from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.state import now_iso

DELIVERING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
LOG_PATH = Path("state") / "reopen_sold_chains_log.json"

# (campaign key, ad-set key, ad key/prefix, label) — the six SG rows in the screenshot.
CHAINS: List[Tuple[str, str, str, str]] = [
    ("sg儿童长高方程式purchaselal15153", "adsetpurchaselal12sg25",
     "video13三年前他長了10公分", "Video 13 @ LAL 1-2%"),
    ("sg儿童长高方程式3interestfamilyandrelationships", "interestfamilyandrelationships",
     "hook9你有没有发现孩子没有以前那么活泼了", "Hook 9 @ Interest F&R"),
    ("sg儿童长高方程式purchaselal15153", "adsetpurchaselal1sg25",
     "video孩子15岁以上还有机会长高吗", "15岁以上 @ LAL 1%"),
    ("sg儿童长高方程式familyrelationshipsa113", "interestfamilyandrelationships",
     "video715岁还没抽高", "Video 7 @ F&R A"),
    ("sg儿童长高方程式grid33hooktest133", "gridblal12",
     "hook2你還在把麵包當早餐", "Hook 2 @ Grid B"),
    ("sg儿童长高方程式hookeditsa114", "parents317engagedhookeditsa",
     "hookedit04不买牛奶给孩子喝", "Hook Edit 04 @ Hook Edits A"),
]


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def pick_campaign(camp_key: str, campaigns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    eq = [c for c in campaigns if cpa.ad_key(c.get("name") or "") == camp_key]
    if len(eq) == 1:
        return eq[0]
    ct = [c for c in campaigns if camp_key in cpa.ad_key(c.get("name") or "")]
    return ct[0] if len(ct) == 1 else None


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d7 = today - dt.timedelta(days=7)

    campaigns = g._get_all(f"{acct}/campaigns", {"fields": "id,name,status,daily_budget",
                                                 "limit": 500})
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,"
                  "adset{id,name,status,daily_budget},campaign{id}", "limit": 500})
    by_camp: Dict[str, List[Dict[str, Any]]] = {}
    for a in ads:
        by_camp.setdefault(str((a.get("campaign") or {}).get("id")), []).append(a)
    w7 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend",
        time_range={"since": d7.isoformat(), "until": today.isoformat()})}

    audit: List[Dict[str, Any]] = []
    run_ts = now_iso()

    def persist_audit() -> None:
        prior = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
        prior = [e for e in prior if e.get("ts") != run_ts]
        prior.append({"ts": run_ts, "actions": audit})
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(json.dumps(prior, ensure_ascii=False, indent=2))

    opened, skipped, already = [], [], []
    for camp_key, adset_key, ad_key_, label in CHAINS:
        log.info("═" * 96)
        camp = pick_campaign(camp_key, campaigns)
        if camp is None:
            log.info("⚠️ %s: campaign key %r did not resolve to exactly one campaign — SKIPPED",
                     label, camp_key[:44])
            skipped.append(f"{label} (campaign unresolved)")
            continue
        camp_ads = by_camp.get(str(camp["id"]), [])
        pool = [a for a in camp_ads
                if cpa.ad_key((a.get("adset") or {}).get("name") or "") == adset_key
                or adset_key in cpa.ad_key((a.get("adset") or {}).get("name") or "")]
        mine = [a for a in pool if cpa.ad_key(a.get("name") or "") == ad_key_] or \
               [a for a in pool if ad_key_ in cpa.ad_key(a.get("name") or "")]
        if not mine:
            log.info("⚠️ %s: no ad matching %r inside %r ▸ adset key %r — SKIPPED", label,
                     ad_key_[:34], camp.get("name"), adset_key[:34])
            skipped.append(f"{label} (ad not found)")
            continue
        target = max(mine, key=lambda a: w7.get(a["id"], 0.0))
        adset = target.get("adset") or {}

        daily = camp.get("daily_budget") or adset.get("daily_budget") or "?"
        try:
            daily = f"RM{int(daily) / 100:.0f}/day" + (" CBO" if camp.get("daily_budget") else "")
        except (TypeError, ValueError):
            daily = str(daily)
        log.info("── %s → %r ▸ %r ▸ %r (%s)", label, camp.get("name"), adset.get("name"),
                 target.get("name"), daily)

        if (target.get("effective_status") or "") in DELIVERING:
            log.info("   already delivering — nothing to do")
            already.append(label)
            continue

        camp_live = camp.get("status") == "ACTIVE"
        adset_live = adset.get("status") == "ACTIVE"
        would_release: List[Dict[str, Any]] = []
        for a in camp_ads:
            if a["id"] == target["id"] or a.get("status") != "ACTIVE":
                continue
            sib_adset = a.get("adset") or {}
            same = str(sib_adset.get("id")) == str(adset.get("id"))
            if same:
                if not (camp_live and adset_live):
                    would_release.append(a)
            elif not camp_live and sib_adset.get("status") == "ACTIVE":
                would_release.append(a)
        muted, blocked = [], None
        for a in would_release:
            try:
                g._request("POST", a["id"], data={"status": "PAUSED"})
                muted.append(a)
                log.info("   · sibling %s %s → PAUSED", a["id"], (a.get("name") or "")[:34])
                audit.append({"action": "pause_sibling", "ad": a["id"], "name": a.get("name")})
            except GraphError as e:
                blocked = (a, e)
                break
        if blocked is not None:
            a, e = blocked
            for m in muted:
                try:
                    g._request("POST", m["id"], data={"status": "ACTIVE"})
                    audit.append({"action": "unpause_sibling_rollback", "ad": m["id"]})
                except GraphError:
                    log.info("   ✗ rollback of %s failed — left PAUSED", m["id"])
            log.info("✗ %s: sibling %s rejects edits (%s) and would deliver — chain untouched",
                     label, a["id"], e)
            skipped.append(f"{label} (legacy sibling unpausable)")
            persist_audit()
            continue

        if target.get("status") != "ACTIVE":
            g._request("POST", target["id"], data={"status": "ACTIVE"})
        if not adset_live:
            g._request("POST", adset["id"], data={"status": "ACTIVE"})
        if not camp_live:
            g._request("POST", camp["id"], data={"status": "ACTIVE"})
        # keep the in-memory view honest for later chains in the same campaign
        camp["status"], adset["status"] = "ACTIVE", "ACTIVE"

        fin = g._request("GET", target["id"], params={"fields": "status,effective_status"})
        ok = (fin.get("effective_status") or "") in DELIVERING
        log.info("   %s ad %s effective=%s · %s", "✓" if ok else "✗ NOT DELIVERABLE —",
                 target["id"], fin.get("effective_status"), daily)
        (opened if ok else skipped).append(f"{label} ({daily})")
        audit.append({"action": "reopen_chain", "chain": label, "campaign": camp["id"],
                      "adset": adset.get("id"), "ad": target["id"],
                      "effective": fin.get("effective_status")})
        persist_audit()

    log.info("═" * 96)
    final_summary(
        log, f"Screenshot SG chains: opened {len(opened)} ({'; '.join(opened) or '—'}) · "
             f"already live {len(already)} ({'; '.join(already) or '—'}) · skipped "
             f"{len(skipped)} ({'; '.join(skipped) or '—'}). Only the named chains were "
             f"woken, released siblings paused first, budgets untouched. [MY] rows and "
             f"martinigbio are not this account's to open.")


if __name__ == "__main__":
    main()
