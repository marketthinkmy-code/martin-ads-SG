"""Reopen ONLY the exact chains that sold: the sale's own campaign → ad set → ad. LIVE.

Operator (30 Aug), after the 誤關 audit found three sold-then-switched-off names:
"就只開有成交的 campaign - ad set - ad 就好"

So nothing is judged here — the Paid Student List rows decide. Every provably-SG sale in the
last 14 days whose ad name is one of the three misclosed names is resolved through its OWN
UTM values (campaign, ad set, ad) to the matching entities in the account, and exactly that
chain is switched on. Everything else stays as the operator left it:

  · before a campaign wakes, every OTHER ad in it that is ad-level ACTIVE is ad-level PAUSED
    first (the enable_seller_campaigns pattern) — so no window exists in which an unproven
    sibling can deliver;
  · budgets are not touched — the chain runs at whatever it already carries (logged);
  · a chain that is already delivering is left alone;
  · a sale whose UTM cannot be matched to exactly one campaign, or whose ad cannot be found
    inside it, is reported and SKIPPED — no guessing about where money goes.

Matching is by the account's standing name-key rule (cpa.ad_key both sides). When one name
runs as several copies inside the sold campaign, the sale's ad-set UTM picks the copy; if
that still leaves several, the copy with the most last-7d spend is taken (the one whose
pause was the actual 誤關). Re-kill safety: all three names have SG sales inside the nightly
monitor's 60-day rescue window, so the CPL guardrail's CPA rescue holds them.

Actions are appended to state/reopen_sold_chains_log.json. Idempotent: a re-run finds the
chains already live and changes nothing.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.state import now_iso

WINDOW_DAYS = 14
DELIVERING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
LOG_PATH = Path("state") / "reopen_sold_chains_log.json"

# The three misclosed names from the 30 Aug audit — the only names this run may touch.
TARGET_NAMES = [
    "Video: 孩子15岁以上还有机会长高吗？",
    "Hook Edit 04：不买牛奶给孩子喝",
    "Hook 9：你有没有发现孩子没有以前那么活泼了？变得越来越安静？自卑？",
]
TARGET_KEYS = {cpa.ad_key(n) for n in TARGET_NAMES}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _sgsale(x) -> bool:
    return ("[sg]" in x.campaign) or ("martin-sg" in x.campaign) or ("martin sg" in x.campaign)


def match_one(key: str, pool: List[Dict[str, Any]], namefield: str = "name"):
    """Exactly-one match by name key: equality first, containment fallback. None if 0 or >1."""
    if not key:
        return None, "empty key"
    eq = [p for p in pool if cpa.ad_key(p.get(namefield) or "") == key]
    if len(eq) == 1:
        return eq[0], "exact"
    if len(eq) > 1:
        return None, f"{len(eq)} exact matches"
    ct = [p for p in pool if key in cpa.ad_key(p.get(namefield) or "")
          or cpa.ad_key(p.get(namefield) or "") in key]
    if len(ct) == 1:
        return ct[0], "containment"
    return None, f"{len(ct)} containment matches"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d14 = today - dt.timedelta(days=WINDOW_DAYS)
    d7 = today - dt.timedelta(days=7)

    # ── the sales that decide: SG, in-window, one of the three names ────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    wanted: List[Tuple[str, str, str, str]] = []       # (camp_key, adset_key, ad_key, date)
    for x in sales:
        k = cpa.ad_key(x.ad)
        if k in TARGET_KEYS and x.date and x.date >= d14 and _sgsale(x):
            wanted.append((cpa.ad_key(x.campaign), cpa.ad_key(x.adset), k, x.date.isoformat()))
    if not wanted:
        final_summary(log, "No provably-SG sale in the window matches the three names — "
                           "nothing to reopen, nothing changed.")
        return
    log.info("── %d qualifying sale(s):", len(wanted))
    for ck, sk, ak, d in wanted:
        log.info("   %s · ad=%s · campaign=%s · adset=%s", d, ak[:30], ck[:40], sk[:30] or "∅")

    # ── the account as it stands ────────────────────────────────────────────────
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
    opened, skipped, already = [], [], []
    done_chains = set()
    for camp_key, adset_key, ad_key_, date in wanted:
        log.info("═" * 96)
        camp, how = match_one(camp_key, campaigns)
        if camp is None:
            log.info("⚠️ %s: campaign UTM %r → %s — SKIPPED, nothing touched", date,
                     camp_key[:40], how)
            skipped.append(f"{date} {ad_key_[:20]} (campaign: {how})")
            continue
        camp_ads = by_camp.get(str(camp["id"]), [])
        mine = [a for a in camp_ads if cpa.ad_key(a.get("name") or "") == ad_key_]
        if not mine:
            log.info("⚠️ %s: ad %r not found inside campaign %r — SKIPPED", date, ad_key_[:30],
                     camp.get("name"))
            skipped.append(f"{date} {ad_key_[:20]} (no ad in campaign)")
            continue
        if len(mine) > 1 and adset_key:
            named = [a for a in mine
                     if cpa.ad_key((a.get("adset") or {}).get("name") or "") == adset_key
                     or adset_key in cpa.ad_key((a.get("adset") or {}).get("name") or "")]
            if named:
                mine = named
        target = max(mine, key=lambda a: w7.get(a["id"], 0.0))
        adset = target.get("adset") or {}
        chain = (str(camp["id"]), str(adset.get("id")), str(target["id"]))
        if chain in done_chains:
            log.info("── %s: chain already handled this run", date)
            continue
        done_chains.add(chain)

        daily = camp.get("daily_budget") or adset.get("daily_budget") or "?"
        try:
            daily = f"RM{int(daily) / 100:.0f}/day"
        except (TypeError, ValueError):
            daily = str(daily)
        log.info("── sale %s → %r ▸ %r ▸ %r (%s match, %s)", date, camp.get("name"),
                 adset.get("name"), target.get("name"), how, daily)

        if (target.get("effective_status") or "") in DELIVERING:
            log.info("   already delivering — nothing to do")
            already.append(target.get("name") or target["id"])
            continue

        # freeze every OTHER ad-level-ACTIVE ad in the campaign BEFORE anything wakes
        for a in camp_ads:
            if a["id"] == target["id"] or a.get("status") != "ACTIVE":
                continue
            g._request("POST", a["id"], data={"status": "PAUSED"})
            chk = g._request("GET", a["id"], params={"fields": "status"})
            log.info("   %s sibling %s %s → %s",
                     "·" if chk.get("status") == "PAUSED" else "✗",
                     a["id"], (a.get("name") or "")[:34], chk.get("status"))
            audit.append({"action": "pause_sibling", "ad": a["id"], "name": a.get("name")})

        # wake the chain bottom-up, only levels that are off
        if target.get("status") != "ACTIVE":
            g._request("POST", target["id"], data={"status": "ACTIVE"})
        if adset.get("status") != "ACTIVE":
            g._request("POST", adset["id"], data={"status": "ACTIVE"})
        if camp.get("status") != "ACTIVE":
            g._request("POST", camp["id"], data={"status": "ACTIVE"})

        fin = g._request("GET", target["id"], params={"fields": "status,effective_status"})
        ok = (fin.get("effective_status") or "") in DELIVERING
        log.info("   %s ad %s effective=%s · budget %s", "✓" if ok else "✗ NOT DELIVERABLE —"
                 " check by hand", target["id"], fin.get("effective_status"), daily)
        (opened if ok else skipped).append(
            f"{(target.get('name') or '')[:30]} @ {(camp.get('name') or '')[:34]} ({daily})")
        audit.append({"action": "reopen_chain", "sale_date": date, "campaign": camp["id"],
                      "adset": adset.get("id"), "ad": target["id"],
                      "effective": fin.get("effective_status")})

    prior = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
    prior.append({"ts": now_iso(), "actions": audit})
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(prior, ensure_ascii=False, indent=2))

    log.info("═" * 96)
    final_summary(
        log, f"Reopened {len(opened)} sold chain(s): {'; '.join(opened) or '—'}. "
             f"Already live: {len(already)}. Skipped: {len(skipped)} "
             f"({'; '.join(skipped) or '—'}). Only the sale's own campaign▸ad set▸ad was "
             f"switched on; every other ad-level-ACTIVE ad in those campaigns was ad-level "
             f"paused first, and budgets were not changed.")


if __name__ == "__main__":
    main()
