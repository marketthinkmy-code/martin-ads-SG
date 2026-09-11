"""CPL guardrail: the operator's 11 Sep 每日广告规则, run against Meta.

"CPL" here means cost per the campaign's optimized conversion event (e.g. Complete
Registration), not a hardcoded "lead". Two daily rules (SG numbers; MY runs its own repo):

  1. Spend >= 1.5 x target CPL with 0 registrations  -> pause the AD.
  2. Window CPL above the target (kpi.cpl_target_myr) -> cut that budget chain's daily
     budget by kpi.cpl_reduce_pct (ABO: the ad set; CBO: the campaign, judged on its
     aggregate). At most one cut per entity per MYT day (state/budget_cuts ledger, pushed
     to main by the workflow), floored at the RM50 ad-set minimum. High CPL with real
     leads is no longer auto-PAUSED — the cut replaces the old kill line.

The decision logic is pure (unit-tested); the runner reads insights via the Graph client,
only ever acts on ACTIVE ads, and never un-pauses — re-activation is always a human (or
weekly_on) decision. cpl_hold names stay exempt; the 60d real-sales CPA rescue and hard
stop still apply to pauses.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import cpa, state
from .logging import final_summary, get_logger
from .settings import KpiCfg, Settings

INSUFFICIENT_SPEND = "insufficient_spend"
ZERO_RESULTS = "zero_results_over_min_spend"
OVER_THRESHOLD = "cpl_over_target"   # 11 Sep rules: above target -> budget CUT, never an ad pause
WITHIN_THRESHOLD = "within_threshold"
NO_RESULTS_YET = "no_results_yet"
MANUAL_HOLD = "manual_hold"  # owner asked to keep this ad running despite CPL
BUDGET_CUT = "cpl_over_target_budget_cut"  # audit reason for a daily -30% budget cut

def _week_start_thursday(today: dt.date) -> dt.date:
    """Most recent Thursday (the weekly ON/reset day) on or before `today`."""
    return today - dt.timedelta(days=(today.weekday() - 3) % 7)  # Mon=0..Thu=3


def cpl_window(settings: Settings, today: dt.date):
    """(date_preset, time_range) for the CPL lookback.

    'week_thu' = week-to-date from the most recent Thursday — the window the operator
    actually reviews (matches the weekly OFF/ON cycle). Anything else is a Meta date_preset.
    """
    lookback = settings.kpi.cpl_lookback
    if lookback == "week_thu":
        return None, {"since": _week_start_thursday(today).isoformat(), "until": today.isoformat()}
    return lookback, None


def result_action_type(conversion_event: str) -> str:
    """The exact insights action_type that equals Ads Manager "Results" for a pixel-optimized ad.

    Meta reports the SAME conversion under several overlapping buckets (complete_registration,
    omni_complete_registration, offsite_complete_registration_*, offsite_conversion.fb_pixel_*),
    so we must match ONE exactly — substring-summing them multiplies the real count.
    """
    return f"offsite_conversion.fb_pixel_{(conversion_event or '').lower()}"


def extract_results(actions: Optional[List[Dict[str, Any]]], action_type: str) -> float:
    """Sum values for ONLY the exact optimized-event bucket (= Ads Manager 'Results')."""
    total = 0.0
    for action in actions or []:
        if action.get("action_type") == action_type:
            try:
                total += float(action.get("value", 0))
            except (TypeError, ValueError):
                continue
    return total


def parse_metrics(insight: Optional[Dict[str, Any]], token: str) -> Tuple[float, float]:
    """Return (spend, results) from a raw insight row for the optimized event."""
    if not insight:
        return 0.0, 0.0
    try:
        spend = float(insight.get("spend", 0) or 0)
    except (TypeError, ValueError):
        spend = 0.0
    return spend, extract_results(insight.get("actions"), token)


def decide(spend: float, results: float, kpi: KpiCfg) -> Tuple[bool, str, Optional[float]]:
    """(should_pause, reason, cpl). cpl is None when undefined, inf when results==0.

    11 Sep 每日规则: the only CPL-driven AD pause left is 1.5 x target spent with zero
    registrations (cpl_min_spend_myr = that line, and also the verdict gate — no judgement
    before it, or before 3 results). Over-target WITH results returns OVER_THRESHOLD with
    should_pause=False: the budget-cut pass handles it at the ad-set/campaign level.
    """
    if spend < kpi.cpl_min_spend_myr and results < 3:
        return False, INSUFFICIENT_SPEND, None
    if results <= 0:
        if kpi.pause_zero_lead_after_spend:
            return True, ZERO_RESULTS, math.inf
        return False, NO_RESULTS_YET, math.inf
    cpl = spend / results
    if cpl > kpi.cpl_target_myr:
        return False, OVER_THRESHOLD, cpl
    return False, WITHIN_THRESHOLD, cpl


@dataclass
class AdDecision:
    ad_id: str
    name: str
    spend: float
    results: float
    cpl: Optional[float]
    should_pause: bool
    reason: str
    cpa: Optional[float] = None     # 60-day real-sales CPA (None when not judged)
    cpa_sales: int = 0              # 60-day matched paid sales
    age_days: Optional[int] = None  # ad age, for the conversion-window guard
    adset_id: Optional[str] = None  # for the budget-cut pass (aggregate per budget chain)


def _mkey(name: str) -> str:
    """Campaign match key: drop a leading '(Image)' tag Meta adds, then normalise."""
    s = (name or "").strip()
    if s.lower().startswith("(image)"):
        s = s[len("(image)"):]
    return cpa.norm(s)


def build_cpa_context(graph, settings: Settings, today: dt.date):
    """(60-day sales by (campaign,ad), 60-day spend by ad_id) for the CPA gate.

    Returns empty dicts when CPA is disabled or any source is unavailable, so a Sheets/Meta
    hiccup degrades the monitor to CPL-only rather than breaking it.
    """
    if not settings.cpa.enabled:
        return {}, {}
    try:
        from .clients.sheets import SheetsClient
        values = SheetsClient(settings.secrets.google_sa_json).read_tab(
            settings.cpa.spreadsheet_id, settings.cpa.sales_tab)
        sales, _cols, _hdr = cpa.parse_sales(values, settings.cpa.price_myr)
        cutoff = today - dt.timedelta(days=60)
        # Match by ad NAME only: the sheet's campaign column is missing/misnamed for some
        # markets (e.g. SG) and its campaign values don't align with Meta campaign names,
        # so keying on (campaign, ad) silently attributed 0 sales and the CPA rescue never
        # fired. ad_key() is width/punctuation-robust so 'MAR Video 5: 林書豪 story' matches
        # the sheet's 'mar video 5：林書豪story'.
        sold: Dict[str, int] = {}
        for s in sales:
            if s.date and s.date > cutoff:
                key = cpa.ad_key(s.ad)
                if key:
                    sold[key] = sold.get(key, 0) + 1
        spend: Dict[str, float] = {}
        for row in graph.account_insights(
                settings.meta.account_path, level="ad", fields="ad_id,spend",
                time_range={"since": cutoff.isoformat(), "until": today.isoformat()}):
            try:
                spend[row.get("ad_id")] = float(row.get("spend") or 0)
            except (TypeError, ValueError):
                continue
        return sold, spend
    except Exception as exc:  # noqa: BLE001
        get_logger().warning("CPA context unavailable (%s) — CPL-only this run", exc)
        return {}, {}


def evaluate_account(graph, settings: Settings, *, cpa_ctx=None) -> List[AdDecision]:
    """Read every active ad in the account and compute per-ad pause decisions (no writes).

    Whole-account scope (every campaign in the Martin MY account), but judged one ad at a time —
    a single bad creative is paused without touching the rest of its ad set or campaign.
    Only ads whose ad set optimizes for the configured conversion event (e.g. Complete
    Registration) are evaluated, so a campaign chasing a different objective can never be
    paused on a registration-CPL it was never trying to produce.
    """
    account = settings.meta.account_path
    token = result_action_type(settings.meta.conversion_event)
    want_event = (settings.meta.conversion_event or "").upper()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()  # MYT
    cpl_preset, cpl_range = cpl_window(settings, today)
    sold60, spend60 = cpa_ctx if cpa_ctx is not None else build_cpa_context(graph, settings, today)
    use_cpa = settings.cpa.enabled and (bool(sold60) or bool(spend60))
    tiers = cpa.CpaTiers(settings.cpa.healthy_max_myr, settings.cpa.max_acceptable_myr,
                         settings.cpa.hard_stop_myr)

    decisions: List[AdDecision] = []
    for campaign in graph.list_campaigns(account):
        if campaign.get("effective_status") != "ACTIVE":  # paused/archived have no live ads
            continue
        for ad in graph.list_ads_under_campaign(campaign["id"]):
            if ad.get("effective_status") != "ACTIVE":
                continue
            promoted = (ad.get("adset") or {}).get("promoted_object") or {}
            if (promoted.get("custom_event_type") or "").upper() != want_event:
                continue  # not optimized for our event — not ours to judge or pause
            name = ad.get("name", ad["id"])
            insight = graph.get_ad_insight(ad["id"], date_preset=cpl_preset, time_range=cpl_range)
            spend, results = parse_metrics(insight, token)

            held = any(h and h in name for h in settings.kpi.cpl_hold)
            if held:                                   # a hold exempts from CPL (not CPA)
                cpl_pause, cpl_reason = False, MANUAL_HOLD
                cpl = (spend / results) if results else (math.inf if spend else None)
            else:
                cpl_pause, cpl_reason, cpl = decide(spend, results, settings.kpi)

            cpa_val: Optional[float] = None
            n_sales, age = 0, None
            should_pause, reason = cpl_pause, cpl_reason
            if use_cpa:
                n_sales = sold60.get(cpa.ad_key(name), 0)
                sp60 = spend60.get(ad["id"], 0.0)
                cpa_val = cpa.cpa(sp60, n_sales)
                created = cpa.parse_date((ad.get("created_time") or "")[:10])
                age = (today - created).days if created else None
                should_pause, reason = cpa.combined_decision(
                    cpl_pause=cpl_pause, cpl_reason=cpl_reason, cpa_value=cpa_val,
                    cpa_sales=n_sales, cpa_spend=sp60, age_days=age, tiers=tiers,
                    conversion_days=settings.cpa.conversion_days, min_spend=settings.cpa.min_spend_myr)

            decisions.append(AdDecision(ad["id"], name, spend, results, cpl, should_pause, reason,
                                        cpa=cpa_val, cpa_sales=n_sales, age_days=age,
                                        adset_id=ad.get("adset_id")))
    return decisions


# ── 11 Sep rule 2: daily -30% budget cut on over-target chains ─────────────────
def plan_budget_cuts(decisions: List[AdDecision], adsets: Dict[str, Dict[str, Any]],
                     campaigns: Dict[str, Dict[str, Any]], kpi: KpiCfg,
                     floor_cents: int, cut_dates: Dict[str, str], today_iso: str
                     ) -> List[Dict[str, Any]]:
    """Pure planner: which budgets to cut today, judged per budget chain.

    Aggregates window spend/results per ad set (ads being paused this run excluded — the
    kill already handles them); a set with no ad-set budget folds into its CBO campaign.
    A chain is cut when it clears the verdict gate, has results, and its aggregate CPL is
    above target — by cpl_reduce_pct, floored at floor_cents, at most once per MYT day
    (cut_dates ledger). A set containing a cpl_hold ad is operator territory: never cut.
    """
    held_sets = {d.adset_id for d in decisions if d.reason == MANUAL_HOLD and d.adset_id}
    agg: Dict[str, List[float]] = {}
    for d in decisions:
        if d.should_pause or not d.adset_id or d.adset_id in held_sets:
            continue
        a = agg.setdefault(d.adset_id, [0.0, 0.0])
        a[0] += d.spend
        a[1] += d.results

    def _cents(v) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    entities: Dict[str, List[float]] = {}          # entity_id -> [spend, results]
    kinds: Dict[str, Tuple[str, Dict[str, Any]]] = {}   # entity_id -> (type, info)
    for sid, (sp, res) in agg.items():
        info = adsets.get(sid) or {}
        if _cents(info.get("daily_budget")) > 0:
            entities[sid] = [sp, res]
            kinds[sid] = ("adset", info)
        else:                                      # CBO — the campaign owns the budget
            cid = info.get("campaign_id") or ""
            cinfo = campaigns.get(cid) or {}
            if _cents(cinfo.get("daily_budget")) > 0:
                e = entities.setdefault(cid, [0.0, 0.0])
                e[0] += sp
                e[1] += res
                kinds[cid] = ("campaign", cinfo)

    plans: List[Dict[str, Any]] = []
    for eid, (sp, res) in entities.items():
        if cut_dates.get(eid) == today_iso:
            continue                               # already cut today — daily rule
        if sp < kpi.cpl_min_spend_myr and res < 3:
            continue                               # verdict gate
        if res <= 0:
            continue                               # zero-reg is the ad-level kill's job
        cpl = sp / res
        if cpl <= kpi.cpl_target_myr:
            continue
        etype, info = kinds[eid]
        cur = _cents(info.get("daily_budget"))
        new = max(floor_cents, int(round(cur * (1.0 - kpi.cpl_reduce_pct / 100.0))))
        plans.append({"id": eid, "type": etype, "name": info.get("name") or eid,
                      "old_cents": cur, "new_cents": new, "cpl": round(cpl, 2),
                      "spend": round(sp, 2), "results": res,
                      "at_floor": cur <= floor_cents})
    return plans


def _label_names(entity: Dict[str, Any]) -> List[str]:
    """adlabels come back as a bare list or as {data: [...]} depending on the edge."""
    labels = entity.get("adlabels") or []
    if isinstance(labels, dict):
        labels = labels.get("data") or []
    return [(l.get("name") or "") for l in labels if isinstance(l, dict)]


def _budget_cut_pass(graph, settings: Settings, decisions: List[AdDecision],
                     *, dry_run: bool) -> int:
    """Fetch budgets, plan today's cuts, apply them.

    The once-per-day guard is STATELESS on Meta: a cut stamps the entity with today's
    "ADBOT_BUDGET_CUT_<date>" ad label, and labeled entities are skipped. (The workflow's
    GITHUB_TOKEN cannot push the repo ledger, and this monitor runs every ~20 minutes —
    a repo-state guard would silently fail and compound the 30% cut thrice an hour.)
    The state/budget_cuts ledger is kept as a best-effort local audit only.
    """
    log = get_logger()
    kpi = settings.kpi
    if kpi.cpl_reduce_pct <= 0:
        return 0
    acct = settings.meta.account_path
    adsets = {a["id"]: a for a in graph._get_all(
        f"{acct}/adsets", {"fields": "id,name,campaign_id,daily_budget,adlabels", "limit": 500})}
    campaigns = {c["id"]: c for c in graph._get_all(
        f"{acct}/campaigns", {"fields": "id,name,daily_budget,adlabels", "limit": 200})}
    today_iso = ((dt.datetime.utcnow() + dt.timedelta(hours=8)).date()).isoformat()
    cut_label = f"ADBOT_BUDGET_CUT_{today_iso}"
    cut_dates: Dict[str, str] = state.load("budget_cuts", default={})
    if not isinstance(cut_dates, dict):
        cut_dates = {}
    for ent in list(adsets.values()) + list(campaigns.values()):
        if cut_label in _label_names(ent):
            cut_dates[ent["id"]] = today_iso          # label on Meta = already cut today
    plans = plan_budget_cuts(decisions, adsets, campaigns, kpi,
                             settings.meta.budget.adset_min_spend_cents, cut_dates, today_iso)
    applied = 0
    for p in plans:
        tag = f"{p['type']} {p['name']}  CPL={p['cpl']:.0f} (spend {p['spend']:.0f} / {p['results']:.0f})"
        if p["at_floor"]:
            log.info("  [AT FLOOR] %s — RM%d/day already at the RM%d minimum, not cut",
                     tag, p["old_cents"] // 100, settings.meta.budget.adset_min_spend_cents // 100)
            continue
        if dry_run:
            log.info("  [WOULD CUT -%.0f%%] %s  RM%d -> RM%d /day", kpi.cpl_reduce_pct, tag,
                     p["old_cents"] // 100, p["new_cents"] // 100)
            continue
        graph.update_daily_budget(p["id"], p["new_cents"])
        cut_dates[p["id"]] = today_iso
        try:                                       # stamp the entity: today's cut is done
            label_id = graph.get_or_create_label(acct, cut_label)
            graph.set_ad_labels(p["id"], [label_id])
        except Exception as exc:  # noqa: BLE001 — cut stands; next run may re-cut, floored
            log.warning("  !! could not label %s with %s (%s) — daily guard weakened",
                        p["id"], cut_label, exc)
        state.append_pause_log(p["id"], p["type"], BUDGET_CUT,
                               {"old_daily_myr": p["old_cents"] / 100.0,
                                "new_daily_myr": p["new_cents"] / 100.0,
                                "cpl": p["cpl"], "spend": p["spend"], "results": p["results"]})
        log.info("  [CUT -%.0f%%] %s  RM%d -> RM%d /day", kpi.cpl_reduce_pct, tag,
                 p["old_cents"] // 100, p["new_cents"] // 100)
        applied += 1
    if applied:
        state.save("budget_cuts", cut_dates)
    return applied


def run(graph, settings: Settings, *, dry_run: bool = False) -> Dict[str, Any]:
    log = get_logger()
    event = settings.meta.conversion_event

    # Operator hold: kpi.monitor_paused_until (ISO date) silences ALL auto-pausing while
    # today (MYT) is before that date — used around webinar nights ("今晚不要關"). The
    # switch expires by itself; no revert commit needed.
    hold_until = (settings.kpi.monitor_paused_until or "").strip()
    if hold_until:
        today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
        until = cpa.parse_date(hold_until)
        if until and today < until:
            summary = (f"CPL monitor on operator hold until {until} (webinar window) — "
                       f"nothing evaluated, nothing paused.")
            final_summary(log, summary)
            return {"evaluated": 0, "paused": 0, "remaining": 0, "dry_run": dry_run,
                    "held_until": str(until)}

    decisions = evaluate_account(graph, settings)
    to_pause = [d for d in decisions if d.should_pause]

    for d in decisions:
        cpl_str = "∞" if d.cpl == math.inf else (f"{d.cpl:.2f}" if d.cpl is not None else "n/a")
        cpa_str = ("" if d.cpa is None else
                   f" CPA={'∞' if d.cpa == math.inf else f'{d.cpa:.0f}'}(60d {d.cpa_sales} sale,{d.age_days}d)")
        verb = "WOULD PAUSE" if (d.should_pause and dry_run) else ("PAUSE" if d.should_pause else "keep")
        log.info("  [%s] %s  spend=%.2f %s=%.0f CPL=%s%s (%s)",
                 verb, d.name, d.spend, event.lower(), d.results, cpl_str, cpa_str, d.reason)

    paused = 0
    if not dry_run:
        for d in to_pause:
            graph.update_status(d.ad_id, "PAUSED")
            state.append_pause_log(d.ad_id, "ad", d.reason,
                                   {"spend": d.spend, "results": d.results,
                                    "cpl": None if d.cpl is None or d.cpl == math.inf else round(d.cpl, 2),
                                    "cpa": None if d.cpa is None or d.cpa == math.inf else round(d.cpa, 2),
                                    "cpa_sales": d.cpa_sales})
            paused += 1

    cuts = _budget_cut_pass(graph, settings, decisions, dry_run=dry_run)

    active_left = len([d for d in decisions if not d.should_pause])
    verb = "would pause" if dry_run else "paused"
    summary = (f"CPL monitor ({event}): evaluated {len(decisions)} active ads, "
               f"{verb} {len(to_pause) if dry_run else paused}, "
               f"{'would cut' if dry_run else 'cut'} {cuts} budget(s) -{settings.kpi.cpl_reduce_pct:.0f}%, "
               f"{active_left} remain (target CPL {settings.kpi.cpl_target_myr:.0f} MYR, "
               f"0-reg kill at {settings.kpi.cpl_min_spend_myr:.0f})")
    final_summary(log, summary)
    return {"evaluated": len(decisions), "paused": (len(to_pause) if dry_run else paused),
            "budget_cuts": cuts, "remaining": active_left, "dry_run": dry_run}
