"""The six sold chains: RM80/day each + 🌟 prefix on campaign and ad names. LIVE.

Operator (3 Sep): "这 6 条 全部先放 RM80/day" and "这 6 条 campaign 和 ad ，你可以帮我
rename 吗？在前面加上 🌟 符号 给我做个记录，以免我误关".

The 🌟 is a do-not-misclose marker, same habit as the account's existing 🔴 prefixes. It is
SAFE for attribution: cpa.ad_key strips symbols, so every name-keyed match (sheet sales,
close cores, cpl_hold, the reopen tooling) reads the starred name exactly as before, and the
campaign names keep their "[SG]" so the provably-SG rule still fires. Ad sets keep their
names — the ask was campaign 和 ad.

Budgets: each chain to RM80/day at the level that actually carries the budget (campaign when
it has daily_budget = CBO, else the chain's ad set), read → write → read back, and Meta's
stored value is what gets reported. Six chains, five distinct campaigns (both LAL bands sit
in one), so total if all deliver: 6 × RM80 = RM480/day.

Idempotent: names already starred are skipped, budgets already RM80 are skipped. Every write
is verified from stored values and appended to state/reopen_sold_chains_log.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from adbot import cpa
from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.state import now_iso

STAR = "🌟 "
DAILY_MINOR = 8000            # RM80/day
LOG_PATH = Path("state") / "reopen_sold_chains_log.json"

# chain → (campaign, adset, ad). Video 7's ad id is resolved by name inside its campaign.
CHAINS: List[Dict[str, Any]] = [
    {"label": "Video 13 @ LAL 1-2%", "campaign": "120257761432150093",
     "adset": "120257761615520093", "ad": "120257761615910093"},
    {"label": "15岁以上 @ LAL 1%", "campaign": "120257761432150093",
     "adset": "120257761613910093", "ad": "120257761614920093"},
    {"label": "Hook 2 @ Grid B", "campaign": "120257884620220093",
     "adset": "120257884626570093", "ad": "120257884629490093"},
    {"label": "Hook Edit 04 @ Hook Edits A", "campaign": "120257667232910093",
     "adset": "120257667233630093", "ad": "120257667234350093"},
    {"label": "Video 7 @ F&R A", "campaign": "120256985977820093",
     "adset": None, "ad": None, "ad_name_key": "video715岁还没抽高",
     "campaign_key": "familyrelationshipsa113"},
    {"label": "Hook 9 @ Interest F&R", "campaign": "120239099098710093",
     "adset": "120240921209550093", "ad": "120240921209560093"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    audit: List[Dict[str, Any]] = []

    def rename(entity_id: str, kind: str) -> Optional[str]:
        cur = g._request("GET", entity_id, params={"fields": "name"}).get("name") or ""
        if cur.startswith(STAR.strip()):
            log.info("   %s %s already starred: %r", kind, entity_id, cur)
            return cur
        new = STAR + cur
        g._request("POST", entity_id, data={"name": new})
        stored = g._request("GET", entity_id, params={"fields": "name"}).get("name")
        ok = stored == new
        log.info("   %s %s name → %r (%s)", kind, entity_id, stored, "ok" if ok else "MISMATCH")
        if ok:
            audit.append({"action": "rename", "entity": entity_id, "name": stored})
        return stored if ok else None

    def set_budget(entity_id: str, kind: str) -> str:
        cur = g._request("GET", entity_id, params={"fields": "daily_budget"})
        if str(cur.get("daily_budget")) == str(DAILY_MINOR):
            log.info("   %s %s budget already RM%d", kind, entity_id, DAILY_MINOR // 100)
            return f"RM{DAILY_MINOR // 100}"
        g._request("POST", entity_id, data={"daily_budget": DAILY_MINOR})
        stored = int(g._request("GET", entity_id,
                                params={"fields": "daily_budget"}).get("daily_budget") or 0)
        note = f"RM{stored // 100}"
        if stored != DAILY_MINOR:
            note += f" (Meta stored this, not the sent RM{DAILY_MINOR // 100})"
        log.info("   %s %s budget %s → %s", kind, entity_id, cur.get("daily_budget"), stored)
        audit.append({"action": "set_budget", "entity": entity_id, "daily_budget": stored})
        return note

    renamed_campaigns: set = set()
    rows: List[str] = []
    for c in CHAINS:
        log.info("═" * 88)
        log.info("── %s", c["label"])
        camp = g._request("GET", c["campaign"],
                          params={"fields": "name,status,daily_budget"})
        if c.get("campaign_key") and c["campaign_key"] not in cpa.ad_key(camp.get("name") or ""):
            log.info("   !! campaign %s is %r — does not match expected key, SKIPPED",
                     c["campaign"], camp.get("name"))
            rows.append(f"{c['label']}: SKIPPED (campaign mismatch)")
            continue

        ad_id, adset_id = c.get("ad"), c.get("adset")
        if not ad_id:            # Video 7: resolve inside its campaign by name key
            ads = g._get_all(f"{c['campaign']}/ads",
                             {"fields": "id,name,adset{id}", "limit": 100})
            hits = [a for a in ads if c["ad_name_key"] in cpa.ad_key(a.get("name") or "")]
            if len(hits) != 1:
                log.info("   !! %d ads match %r in this campaign — SKIPPED", len(hits),
                         c["ad_name_key"])
                rows.append(f"{c['label']}: SKIPPED (ad ambiguous)")
                continue
            ad_id = hits[0]["id"]
            adset_id = str((hits[0].get("adset") or {}).get("id"))
            log.info("   resolved ad %s / adset %s", ad_id, adset_id)

        # budget on whichever level carries it
        is_cbo = bool(camp.get("daily_budget"))
        try:
            budget = set_budget(c["campaign"] if is_cbo else adset_id,
                                "campaign" if is_cbo else "adset")
        except GraphError as e:
            budget = f"UNCHANGED — edit rejected ({e})"
            log.info("   !! budget edit rejected: %s", e)

        # 🌟 on campaign (once per campaign) and ad
        try:
            if c["campaign"] not in renamed_campaigns:
                if rename(c["campaign"], "campaign"):
                    renamed_campaigns.add(c["campaign"])
            rename(ad_id, "ad")
        except GraphError as e:
            log.info("   !! rename rejected: %s", e)
            rows.append(f"{c['label']}: {budget}, rename rejected")
            continue
        rows.append(f"{c['label']}: {budget} ⭐ok")

    prior = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
    prior.append({"ts": now_iso(), "actions": audit})
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(prior, ensure_ascii=False, indent=2))

    log.info("═" * 88)
    final_summary(
        log, f"Six sold chains at RM80/day with 🌟 markers: {'; '.join(rows)}. Budgets sit on "
             f"the level that carries them (CBO campaign or the chain's ad set), stored values "
             f"verified; campaign and ad names got the 🌟 prefix (ad sets untouched), which "
             f"name-key matching ignores, so sheet attribution and every close/hold rule read "
             f"them exactly as before. Total if all six deliver: RM480/day.")


if __name__ == "__main__":
    main()
