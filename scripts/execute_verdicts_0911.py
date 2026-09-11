"""Execute the operator-approved 11 Sep verdicts. MUTATING — exactly two actions.

Operator approved ("执行") the 11 Sep verdict table:
  1. 关: the NON-🌟 "Video 13：三年前他長了10公分" copy in the PURCHASE LAL campaign
     (RM50/day ad set) — 14d CPL RM118 past the kill line, name-key lifetime CPA RM3,331.
     Pause the ad AND its ad set so nothing dangles.
  2. 调低: the 🌟 Video 13 copy's ad set RM100 -> RM50/day (kept: 60d sales, CPL RM71).

Strict resolution: exactly one ACTIVE campaign whose name contains "PURCHASE LAL"; inside
it exactly one ACTIVE starred and one ACTIVE un-starred ad with the Video 13 name key;
budgets verified against the verdict data (RM50 / RM100) before touching anything —
mismatch or ambiguity aborts with nothing changed. Idempotent on re-run.
"""
from __future__ import annotations

from adbot import cpa, state
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

KEY = cpa.ad_key("Video 13：三年前他長了10公分")
STAR = "🌟"
FLOOR_CENTS = 5000


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    camps = [c for c in g._get_all(f"{acct}/campaigns",
                                   {"fields": "id,name,effective_status", "limit": 200})
             if c.get("effective_status") == "ACTIVE" and "PURCHASE LAL" in (c.get("name") or "")]
    if len(camps) != 1:
        raise SystemExit(f"!! expected exactly 1 ACTIVE 'PURCHASE LAL' campaign, found {len(camps)} — aborting.")
    camp = camps[0]
    log.info("campaign: %s (%s)", camp["name"], camp["id"])

    adsets = {a["id"]: a for a in g._get_all(
        f"{camp['id']}/adsets", {"fields": "id,name,daily_budget,effective_status", "limit": 100})}
    ads = [a for a in g._get_all(
        f"{camp['id']}/ads", {"fields": "id,name,adset_id,effective_status", "limit": 100})
        if a.get("effective_status") == "ACTIVE" and cpa.ad_key(a.get("name") or "") == KEY]
    plain = [a for a in ads if STAR not in (a.get("name") or "")]
    starred = [a for a in ads if STAR in (a.get("name") or "")]
    if len(plain) != 1 or len(starred) != 1:
        raise SystemExit(f"!! expected 1 starred + 1 plain ACTIVE Video 13 copy, "
                         f"found starred={len(starred)} plain={len(plain)} — aborting.")
    kill_ad, keep_ad = plain[0], starred[0]
    kill_set = adsets.get(kill_ad.get("adset_id")) or {}
    keep_set = adsets.get(keep_ad.get("adset_id")) or {}

    kill_budget = int(kill_set.get("daily_budget") or 0)
    keep_budget = int(keep_set.get("daily_budget") or 0)
    log.info("kill target: ad %s (%s) in set %s (RM%d/day)",
             kill_ad["name"], kill_ad["id"], kill_set.get("name"), kill_budget // 100)
    log.info("turn-down target: ad %s (%s) in set %s (RM%d/day)",
             keep_ad["name"], keep_ad["id"], keep_set.get("name"), keep_budget // 100)
    if kill_budget != 5000:
        raise SystemExit(f"!! kill target's ad set is RM{kill_budget/100:.0f}/day, expected RM50 "
                         f"(structure changed since the verdict) — aborting untouched.")
    if keep_budget not in (10000, FLOOR_CENTS):
        raise SystemExit(f"!! 🌟 set is RM{keep_budget/100:.0f}/day, expected RM100 (or already RM50) "
                         f"— aborting untouched.")

    # 1) 关: pause ad, then its ad set
    g.update_status(kill_ad["id"], "PAUSED")
    g.update_status(kill_set["id"], "PAUSED")
    state.append_pause_log(kill_ad["id"], "ad", "operator_verdict_0911_close",
                           {"campaign": camp["name"], "adset_id": kill_set["id"],
                            "note": "14d CPL 118 > kill line; key CPA 3331 > hard stop"})
    after_ad = g.get_object(kill_ad["id"], "status")
    after_set = g.get_object(kill_set["id"], "status")
    log.info("① 关 done: ad -> %s · ad set -> %s", after_ad.get("status"), after_set.get("status"))

    # 2) 调低: 🌟 set RM100 -> RM50 (skip if already there)
    if keep_budget == FLOOR_CENTS:
        log.info("② 调低 skipped: 🌟 set already at RM50/day (re-run).")
    else:
        g.update_daily_budget(keep_set["id"], FLOOR_CENTS)
        state.append_pause_log(keep_set["id"], "adset", "operator_verdict_0911_reduce",
                               {"campaign": camp["name"], "old_daily_myr": keep_budget / 100.0,
                                "new_daily_myr": 50.0, "note": "CPL 71 dear; key CPA over hard stop"})
        after = g.get_object(keep_set["id"], "daily_budget,status")
        log.info("② 调低 done: 🌟 set daily_budget -> RM%d/day (status %s)",
                 int(after.get("daily_budget") or 0) // 100, after.get("status"))

    final_summary(log, "11 Sep verdicts executed: non-🌟 Video 13 ad+adset PAUSED; "
                       "🌟 Video 13 ad set at RM50/day. Nothing else touched.")


if __name__ == "__main__":
    main()
