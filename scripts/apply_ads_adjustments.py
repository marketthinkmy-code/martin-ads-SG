"""Apply the SG Ads Manager adjustments — operator-approved 2026-08-07 (“全部你都做”). LIVE.

Four actions, each guarded and fully audit-logged; a failure in one never aborts the others:

  1. TRIM — for two expensive-but-over-duplicated winners (孩子15岁以上, 我不会买牛奶) keep the
     single highest-30d-spend ACTIVE copy and PAUSE the rest. Copies in a *Scale-Winners*
     campaign and [BRUNEI] copies are left untouched.
  2. SCALE — for two cheap proven winners (新马版牛奶迷思 V8(1), dec hook 13) raise the budget of
     the ad set / campaign holding their best live copy by +50%, capped RM200/day, only if it is
     currently < RM200/day and its campaign name contains no "scale" (so no scale line is touched).
  3. REOPEN — three cheap dead winners (single image 4个月长3cm / 初经, Video 8 麵包牛奶): activate a
     PAUSED copy only when its parent ad set is effectively ACTIVE (else report blocked).
  4. ACTIVATE — the new 1-1-1 Video 12 campaign + ad set + ad.

Scale-Winners budgets are never touched. Everything is in the SG account only.
"""
from __future__ import annotations

import datetime as dt

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ad_key = cpa.ad_key

TRIM = [("孩子15岁以上", "孩子15岁以上"), ("我不会买牛奶 MAR V1", "我不会买牛奶")]
SCALE = [("新马版牛奶迷思 V8(1)", "新马版主打牛奶迷思"), ("dec hook 13", "花了几千块")]
REOPEN = [("single image 4个月长3cm", "4个月长3cm"),
          ("single image 初经", "初经"),
          ("Video 8 麵包牛奶", "麵包牛奶")]
V12 = {"campaign": "120257269400010093", "adset": "120257269400410093", "ad": "120257269401020093"}

BUMP = 1.5          # +50%
CAP_CENTS = 20000   # RM200/day ceiling


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _camp(a):
    return (a.get("campaign") or {}).get("name", "")


def _is_scalewinners(name: str) -> bool:
    c = (name or "").lower()
    return "scale-winners" in c or "scale winners" in c


def _has_scale(name: str) -> bool:
    return "scale" in (name or "").lower()


def _is_brunei(name: str) -> bool:
    c = (name or "").strip().lower()
    return c.startswith("[brunei]") or "brunei" in c[:14]


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
    log.info("pulled %d ads · 30d spend for %d ads", len(ads), len(sp30))
    summary = []

    # ── 1. TRIM ──────────────────────────────────────────────────────────────
    log.info("═" * 92)
    log.info("ACTION 1 · TRIM redundant live copies (keep highest-30d-spend, pause rest)")
    for label, core in TRIM:
        ck = ad_key(core)
        cands = [a for a in ads if ck in ad_key(a.get("name", ""))
                 and a.get("status") == "ACTIVE"
                 and not _is_scalewinners(_camp(a)) and not _is_brunei(_camp(a))]
        prot = [a for a in ads if ck in ad_key(a.get("name", ""))
                and a.get("status") == "ACTIVE" and _is_scalewinners(_camp(a))]
        log.info("─ %s: %d trimmable live copy(ies) (+%d protected in Scale-Winners)",
                 label, len(cands), len(prot))
        if len(cands) <= 1:
            summary.append(f"TRIM {label}: nothing to trim ({len(cands)} live copy)")
            for a in cands:
                log.info("   ✓ keep (only copy) %s RM%.0f · %s", a["id"], sp30.get(a["id"], 0), _camp(a)[:40])
            continue
        cands.sort(key=lambda a: -sp30.get(a["id"], 0.0))
        keep, rest = cands[0], cands[1:]
        log.info("   ✓ KEEP %s · 30d RM%.0f · %s", keep["id"], sp30.get(keep["id"], 0), _camp(keep)[:42])
        paused = 0
        for a in rest:
            try:
                g.update_status(a["id"], "PAUSED")
                paused += 1
                log.info("   ⏸ PAUSED %s · 30d RM%.0f · %s", a["id"], sp30.get(a["id"], 0), _camp(a)[:42])
            except Exception as e:  # noqa: BLE001
                log.warning("   ✗ pause failed %s: %s", a["id"], e)
        summary.append(f"TRIM {label}: kept 1, paused {paused} (protected {len(prot)} in Scale-Winners)")

    # ── 2. SCALE ─────────────────────────────────────────────────────────────
    log.info("═" * 92)
    log.info("ACTION 2 · SCALE budget of best live copy (+50%%, cap RM200, skip any 'scale' campaign)")
    for label, core in SCALE:
        ck = ad_key(core)
        cands = [a for a in ads if ck in ad_key(a.get("name", ""))
                 and a.get("status") == "ACTIVE" and not _is_brunei(_camp(a))]
        if not cands:
            summary.append(f"SCALE {label}: no ACTIVE copy found — skipped")
            log.info("─ %s: no ACTIVE copy — skip", label)
            continue
        cands.sort(key=lambda a: -sp30.get(a["id"], 0.0))
        best = cands[0]
        camp = best.get("campaign") or {}
        adset = best.get("adset") or {}
        if _has_scale(camp.get("name", "")):
            summary.append(f"SCALE {label}: best copy is in a scale campaign ({camp.get('name','')[:30]}) — left alone")
            log.info("─ %s: best copy in scale campaign %r — skip", label, camp.get("name", "")[:40])
            continue
        if camp.get("daily_budget"):
            ent_id, cur, lvl, ent_name = camp["id"], int(camp["daily_budget"]), "campaign(CBO)", camp.get("name", "")
        elif adset.get("daily_budget"):
            ent_id, cur, lvl, ent_name = adset["id"], int(adset["daily_budget"]), "adset(ABO)", adset.get("name", "")
        else:
            summary.append(f"SCALE {label}: no daily_budget on campaign/adset (lifetime?) — skipped")
            log.info("─ %s: no daily_budget found — skip", label)
            continue
        siblings = sum(1 for a in ads if (a.get("campaign") or {}).get("id") == camp.get("id")
                       and a.get("status") == "ACTIVE" and ad_key(a.get("name", "")) != ck)
        if cur >= CAP_CENTS:
            summary.append(f"SCALE {label}: {lvl} already RM{cur/100:.0f} (≥RM200) — left alone")
            log.info("─ %s: %s already RM%.0f ≥ cap — skip", label, lvl, cur / 100)
            continue
        new = min(int(cur * BUMP), CAP_CENTS)
        try:
            g._request("POST", ent_id, data={"daily_budget": str(new)})
            log.info("─ %s: %s %r  RM%.0f → RM%.0f/day  (+%d other active ad(s) in it)",
                     label, lvl, ent_name[:38], cur / 100, new / 100, siblings)
            summary.append(f"SCALE {label}: {lvl} RM{cur/100:.0f}→RM{new/100:.0f}/day "
                           f"({ent_name[:28]}; lifts {siblings} sibling ad(s) too)")
        except Exception as e:  # noqa: BLE001
            log.warning("─ %s: budget bump failed: %s", label, e)
            summary.append(f"SCALE {label}: budget bump FAILED ({e})")

    # ── 3. REOPEN ───────────────────────────────────────────────────────────
    log.info("═" * 92)
    log.info("ACTION 3 · REOPEN cheap dead winners (only if parent ad set is ACTIVE)")
    for label, core in REOPEN:
        ck = ad_key(core)
        matches = [a for a in ads if ck in ad_key(a.get("name", "")) and not _is_brunei(_camp(a))]
        reop = blocked = live = 0
        for a in matches:
            aset_eff = (a.get("adset") or {}).get("effective_status")
            if a.get("status") == "PAUSED" and aset_eff == "ACTIVE":
                try:
                    g.update_status(a["id"], "ACTIVE")
                    reop += 1
                    log.info("   ▶ REOPENED %s · %s", a["id"], _camp(a)[:42])
                except Exception as e:  # noqa: BLE001
                    log.warning("   ✗ reopen failed %s: %s", a["id"], e)
            elif a.get("status") == "PAUSED":
                blocked += 1
            elif a.get("status") == "ACTIVE":
                live += 1
        bits = []
        if reop:
            bits.append(f"▶ reopened {reop}")
        if live:
            bits.append(f"already live {live}")
        if blocked:
            bits.append(f"⏸ {blocked} blocked (parent paused)")
        log.info("─ %s: %d match · %s", label, len(matches), ", ".join(bits) or "no action")
        summary.append(f"REOPEN {label}: {', '.join(bits) or 'no live-safe copy — blocked/none'}")

    # ── 4. ACTIVATE Video 12 1-1-1 ──────────────────────────────────────────
    log.info("═" * 92)
    log.info("ACTION 4 · ACTIVATE 1-1-1 Video 12 (campaign + adset + ad)")
    ok = []
    for kind, eid in (("campaign", V12["campaign"]), ("adset", V12["adset"]), ("ad", V12["ad"])):
        try:
            g.update_status(eid, "ACTIVE")
            ok.append(kind)
            log.info("   ▶ %s %s → ACTIVE", kind, eid)
        except Exception as e:  # noqa: BLE001
            log.warning("   ✗ %s %s activate failed: %s", kind, eid, e)
    summary.append(f"ACTIVATE Video 12: {', '.join(ok) or 'FAILED'} set ACTIVE (RM100/day)")

    log.info("═" * 92)
    for line in summary:
        log.info("  • %s", line)
    final_summary(log, "SG adjustments applied — trim redundant winners · scale cheap winners "
                       "(≤RM200) · reopen deliver-safe cheap winners · activate 1-1-1 Video 12. "
                       "Scale-Winners budgets untouched. Review in Ads Manager.")


if __name__ == "__main__":
    main()
