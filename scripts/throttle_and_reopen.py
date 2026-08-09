"""Throttle the two low-ROAS SG bleeders (reduce budget, do NOT pause) + reopen 什麼樣的孩子.

Operator chose "B 降" 2026-08-09. LIVE, guarded, audited.

  · THROTTLE — for 孩子15岁以上 and 我不会买牛奶, find the highest-30d-spend ACTIVE copy and cut
    the daily budget of its parent (campaign CBO or ad set ABO) by 40% (floor RM50/day).
    SKIP (and report, recommending a pause instead) if that budget pool is a Scale-Winners
    or a 1-1-5 winner stack, or if it also holds a scaled winner (新马版牛奶迷思 / dec hook 13) —
    so throttling a bleeder never drags a winner down with it. [BRUNEI] copies ignored.
  · REOPEN — 什麼樣的孩子: reactivate an Off/PAUSED copy only when its parent ad set is
    effectively ACTIVE (30d SG CPA ~345 justifies it; the 4-day CPL spike does not).
"""
from __future__ import annotations

import datetime as dt

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ad_key = cpa.ad_key

BLEEDERS = [("孩子15岁以上", "孩子15岁以上"), ("我不会买牛奶", "我不会买牛奶")]
REOPEN = [("什麼樣的孩子", "什麼樣的孩子")]
WINNER_CORES = [ad_key("新马版主打牛奶迷思"), ad_key("花了几千块")]  # scaled winners to shield
REDUCE = 0.60          # keep 60% = -40%
FLOOR_CENTS = 5000     # RM50/day floor


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _camp(a):
    return (a.get("campaign") or {}).get("name", "")


def _is_brunei(name: str) -> bool:
    c = (name or "").strip().lower()
    return c.startswith("[brunei]") or "brunei" in c[:14]


def _protected_pool(name: str) -> bool:
    n = (name or "").lower()
    return ("scale-winners" in n) or ("scale winners" in n) or ("1-1-5" in n) or ("1 1 5" in n)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = (today - dt.timedelta(days=30)).isoformat()

    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,"
                  "campaign{id,name,daily_budget,effective_status},"
                  "adset{id,name,daily_budget,effective_status}", "limit": 500})
    sp30 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", time_range={"since": d30, "until": today.isoformat()})}
    log.info("pulled %d ads · 30d spend for %d", len(ads), len(sp30))
    summary = []

    # ── THROTTLE bleeders ───────────────────────────────────────────────────────
    log.info("═" * 92)
    log.info("THROTTLE (−40%%, floor RM50, do NOT pause; shield Scale-Winners & 1-1-5 & winners)")
    for label, core in BLEEDERS:
        ck = ad_key(core)
        cands = [a for a in ads if ck in ad_key(a.get("name", ""))
                 and a.get("status") == "ACTIVE" and not _is_brunei(_camp(a))]
        if not cands:
            summary.append(f"THROTTLE {label}: no ACTIVE copy — skipped")
            log.info("─ %s: no ACTIVE copy", label)
            continue
        cands.sort(key=lambda a: -sp30.get(a["id"], 0.0))
        heavy = cands[0]
        camp = heavy.get("campaign") or {}
        adset = heavy.get("adset") or {}
        log.info("─ %s: heavy copy %s · 30d RM%.0f · camp %r",
                 label, heavy["id"], sp30.get(heavy["id"], 0), camp.get("name", "")[:44])
        if _protected_pool(camp.get("name", "")):
            summary.append(f"THROTTLE {label}: heavy copy in protected pool "
                           f"({camp.get('name','')[:30]}) → NOT touched; pause that copy instead if wanted")
            log.info("   ⛔ protected pool — skip (recommend pause the copy instead)")
            continue
        # budget location
        if camp.get("daily_budget"):
            ent_id, cur, lvl, ent_name = camp["id"], int(camp["daily_budget"]), "campaign(CBO)", camp.get("name", "")
            pool_ads = [a for a in ads if (a.get("campaign") or {}).get("id") == camp.get("id")]
        elif adset.get("daily_budget"):
            ent_id, cur, lvl, ent_name = adset["id"], int(adset["daily_budget"]), "adset(ABO)", adset.get("name", "")
            pool_ads = [a for a in ads if (a.get("adset") or {}).get("id") == adset.get("id")]
        else:
            summary.append(f"THROTTLE {label}: no daily_budget (lifetime?) — skipped")
            log.info("   no daily_budget — skip")
            continue
        winner_here = [a for a in pool_ads if a.get("status") == "ACTIVE"
                       and any(w in ad_key(a.get("name", "")) for w in WINNER_CORES)]
        if winner_here:
            wn = (winner_here[0].get("name") or "")[:24]
            summary.append(f"THROTTLE {label}: {lvl} pool also holds a scaled winner ({wn}) → "
                           f"NOT touched (would throttle the winner); pause the bleeder copy instead if wanted")
            log.info("   ⛔ pool holds scaled winner %r — skip to protect it", wn)
            continue
        sib = sum(1 for a in pool_ads if a.get("status") == "ACTIVE"
                  and ad_key(a.get("name", "")) != ck)
        new = max(int(cur * REDUCE), FLOOR_CENTS)
        if new >= cur:
            summary.append(f"THROTTLE {label}: {lvl} already RM{cur/100:.0f} ≤ floor — left")
            log.info("   already ≤ floor — skip")
            continue
        try:
            g._request("POST", ent_id, data={"daily_budget": str(new)})
            log.info("   ✓ %s %r  RM%.0f → RM%.0f/day  (pool has %d other active ad(s))",
                     lvl, ent_name[:36], cur / 100, new / 100, sib)
            summary.append(f"THROTTLE {label}: {lvl} RM{cur/100:.0f}→RM{new/100:.0f}/day "
                           f"({ent_name[:26]}; −40%; {sib} sibling ad(s) also affected)")
        except Exception as e:  # noqa: BLE001
            log.warning("   ✗ budget cut failed: %s", e)
            summary.append(f"THROTTLE {label}: FAILED ({e})")

    # ── REOPEN 什麼樣的孩子 ──────────────────────────────────────────────────────
    log.info("═" * 92)
    log.info("REOPEN 什麼樣的孩子 (only where parent ad set is ACTIVE)")
    for label, core in REOPEN:
        ck = ad_key(core)
        matches = [a for a in ads if ck in ad_key(a.get("name", "")) and not _is_brunei(_camp(a))]
        reop = blocked = live = 0
        for a in matches:
            aset_eff = (a.get("adset") or {}).get("effective_status")
            if a.get("status") != "ACTIVE" and aset_eff == "ACTIVE":
                try:
                    g.update_status(a["id"], "ACTIVE")
                    reop += 1
                    log.info("   ▶ REOPENED %s · %s", a["id"], _camp(a)[:44])
                except Exception as e:  # noqa: BLE001
                    log.warning("   ✗ reopen failed %s: %s", a["id"], e)
            elif a.get("status") != "ACTIVE":
                blocked += 1
            else:
                live += 1
        bits = []
        if reop:
            bits.append(f"▶ reopened {reop}")
        if live:
            bits.append(f"already live {live}")
        if blocked:
            bits.append(f"⏸ {blocked} blocked (parent paused)")
        log.info("─ %s: %d match · %s", label, len(matches), ", ".join(bits) or "no action")
        summary.append(f"REOPEN {label}: {', '.join(bits) or 'no live-safe copy'}")

    log.info("═" * 92)
    for line in summary:
        log.info("  • %s", line)
    final_summary(log, "Throttle bleeders (−40%, not paused; winners/Scale-Winners/1-1-5 shielded) + "
                       "reopen 什麼樣的孩子. Review in Ads Manager; a fuller CPA read is due ~1 week out.")


if __name__ == "__main__":
    main()
