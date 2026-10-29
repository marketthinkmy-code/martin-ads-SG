"""CPL guardrail: the operator's 11 Sep 每日广告规则, run against Meta.

"CPL" here means cost per the campaign's optimized conversion event (e.g. Complete
Registration), not a hardcoded "lead". Two daily rules (SG numbers; MY runs its own repo):

  1. Spend >= 1.5 x target CPL with 0 registrations  -> pause the AD.
  2. Window CPL above the target (kpi.cpl_target_myr) -> cut that budget chain's daily
     budget by kpi.cpl_reduce_pct (ABO: the ad set; CBO: the campaign, judged on its
     aggregate). At most one cut per entity per MYT day (state/budget_cuts ledger, pushed
     to main by the workflow), floored at the RM50 ad-set minimum. High CPL with real
     leads is no longer auto-PAUSED — the cut replaces the old kill line.

29 Oct operator 「B」: config turns rule 2 off (kpi.cpl_reduce_pct 0) and drops the CPL > 105 kill
(kpi.high_cpl_kill_multiple 0); the RM90 zero-registration kill stays, and a sale only protects an
ad when its UTM campaign, ad set and ad are all this ad's own (sale_key).
29 Oct operator 「加 20%」「A」: an ad whose own 60-day CPA is at or under cpa.target_myr (on enough
spend, any age) gets its budget owner raised by cpa.scale_up_pct, then left
alone for cpa.scale_up_wait_days full days.

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
BUDGET_RAISE = "cpa_within_target_budget_raise"  # 29 Oct: audit reason for a +20% raise
CAMPAIGN_ZERO_RESULTS = "campaign_zero_results_over_line"
HIGH_CPL_NO_SALES = "cpl_over_kill_multiple_no_sales"  # 19 Oct: CPL > 1.5x target and no 60d sale -> pause
HIGH_CPL_HAS_SALES = "cpl_over_kill_multiple_has_sales"
HARD_STOP_EXEMPT = "cpa_hard_stop_exempt"   # operator kept this ad past the CPA hard stop  # same CPL, but it sold -> keep  # 9 Oct: whole CBO test campaign, 0 reg past its line

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
    mult = kpi.high_cpl_kill_multiple or 0.0
    if mult > 0 and cpl > kpi.cpl_target_myr * mult:
        # 19 Oct operator 「CPL 超过 105、又没有成交的，直接关」: candidate pause. Whether it
        # sold is only known in evaluate_account, which keeps it when it has 60d sales.
        return True, HIGH_CPL_NO_SALES, cpl
    if cpl > kpi.cpl_target_myr:
        return False, OVER_THRESHOLD, cpl
    return False, WITHIN_THRESHOLD, cpl


def kpi_for_campaign(kpi: KpiCfg, campaign_name: str) -> KpiCfg:
    """The KPI block with any per-campaign 0-reg kill-line override applied (first match wins)."""
    name = campaign_name or ""
    for o in kpi.cpl_min_spend_overrides or []:
        sub = str(o.get("campaign_contains") or "")
        if sub and sub in name:
            try:
                line = float(o.get("min_spend_myr"))
            except (TypeError, ValueError):
                continue
            return kpi.model_copy(update={"cpl_min_spend_myr": line})
    return kpi


def campaign_zero_lead_line(kpi: KpiCfg, campaign_name: str) -> Optional[float]:
    """RM line past which a matching test CAMPAIGN with zero registrations is paused whole.

    9 Oct operator (1 到 4 都做): a CBO campaign spreads RM100/day over six ads, so no single
    ad reaches the per-ad RM80 line while the campaign keeps burning. The per-campaign entry
    in kpi.cpl_min_spend_overrides may carry campaign_zero_lead_spend_myr for that case.
    None = no campaign-level line for this campaign (first matching entry wins).
    """
    name = campaign_name or ""
    for o in kpi.cpl_min_spend_overrides or []:
        sub = str(o.get("campaign_contains") or "")
        if sub and sub in name:
            raw = o.get("campaign_zero_lead_spend_myr")
            if raw is None:
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    return None


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
    cpa_spend: float = 0.0          # 60-day spend behind the CPA (raise gate)


def _mkey(name: str) -> str:
    """Campaign match key: drop a leading '(Image)' tag Meta adds, then normalise."""
    s = (name or "").strip()
    if s.lower().startswith("(image)"):
        s = s[len("(image)"):]
    return cpa.norm(s)


def sale_key(campaign: str, adset: str, ad: str) -> Tuple[str, str, str]:
    """(campaign, ad set, ad) key shared by the sheet's UTM values and Meta names.

    29 Oct operator 「自己的 campaign，ad set，ad 还没有自己的成交，就关」: a sale protects an ad
    only when all three of its UTM names are this ad's own.
    """
    return cpa.ad_key(campaign), cpa.ad_key(adset), cpa.ad_key(ad)


def build_cpa_context(graph, settings: Settings, today: dt.date):
    """(60-day sales by sale_key(campaign, ad set, ad), 60-day spend by ad_id) for the CPA gate.

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
        # 24 Oct operator 「修」: a sale counts only for the campaign whose UTM it carries. Keyed
        # by ad name alone, one old SG sale of a video protected every new copy of it from
        # the RM90 zero-registration kill (HK 15岁以上 Health and Wellness: RM138.73, 0 reg, kept).
        # The SG UTM campaign now carries {{campaign.name}}; sale_key() folds width and
        # punctuation on both parts so the sheet value matches the Meta name.
        sold: Dict[Tuple[str, str, str], int] = {}
        for s in sales:
            if s.date and s.date > cutoff:
                key = sale_key(s.campaign, s.adset, s.ad)
                if all(key):
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
                cpl_pause, cpl_reason, cpl = decide(
                    spend, results, kpi_for_campaign(settings.kpi, campaign.get("name") or ""))

            cpa_val: Optional[float] = None
            n_sales, age = 0, None
            should_pause, reason = cpl_pause, cpl_reason
            if use_cpa:
                adset_name = (ad.get("adset") or {}).get("name") or ""
                n_sales = sold60.get(sale_key(campaign.get("name") or "", adset_name, name), 0)
                sp60 = spend60.get(ad["id"], 0.0)
                cpa_val = cpa.cpa(sp60, n_sales)
                created = cpa.parse_date((ad.get("created_time") or "")[:10])
                age = (today - created).days if created else None
                should_pause, reason = cpa.combined_decision(
                    cpl_pause=cpl_pause, cpl_reason=cpl_reason, cpa_value=cpa_val,
                    cpa_sales=n_sales, cpa_spend=sp60, age_days=age, tiers=tiers,
                    conversion_days=settings.cpa.conversion_days, min_spend=settings.cpa.min_spend_myr)

            if reason == cpa.HARD_STOP and ad["id"] in settings.cpa.hard_stop_exempt_ad_ids:
                # operator exemption from the CPA line only; the CPL lines still apply
                should_pause, reason = (cpl_pause, cpl_reason) if cpl_pause else (False, HARD_STOP_EXEMPT)

            if cpl_reason == HIGH_CPL_NO_SALES:
                # never kill on registration cost without knowing whether it sold
                if not use_cpa:
                    should_pause, reason = False, OVER_THRESHOLD
                elif n_sales > 0 and reason != cpa.HARD_STOP:
                    should_pause, reason = False, HIGH_CPL_HAS_SALES

            decisions.append(AdDecision(ad["id"], name, spend, results, cpl, should_pause, reason,
                                        cpa=cpa_val, cpa_sales=n_sales, age_days=age,
                                        adset_id=ad.get("adset_id"),
                                        cpa_spend=spend60.get(ad["id"], 0.0) if use_cpa else 0.0))
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
        etype0, info0 = kinds[eid]
        cname = (info0.get("name") if etype0 == "campaign"
                 else (campaigns.get(info0.get("campaign_id") or "") or {}).get("name")) or ""
        if sp < kpi_for_campaign(kpi, cname).cpl_min_spend_myr and res < 3:
            continue                               # verdict gate (per-campaign override aware)
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


# ── 29 Oct operator 「加 20%」「A」: automatic raise on CPA within target ──────────
RAISE_LABEL = "ADBOT_BUDGET_UP_"


def raise_qualifies(d: AdDecision, cfg) -> bool:
    """The ad's own sales put its CPA at or under target, on enough spend. No age gate (29 Oct
    operator 「不需要写死上线天数」: a new ad that sells right away can be raised)."""
    return (not d.should_pause and d.cpa_sales > 0 and d.cpa is not None and d.cpa != math.inf
            and d.cpa <= cfg.target_myr and d.cpa_spend >= cfg.min_spend_myr)


def plan_budget_raises(decisions: List[AdDecision], adsets: Dict[str, Dict[str, Any]],
                       campaigns: Dict[str, Dict[str, Any]], cfg, last_raise: Dict[str, dt.date],
                       today: dt.date) -> List[Dict[str, Any]]:
    """Pure planner: which budgets to raise by cfg.scale_up_pct today.

    One raise per budget chain (ABO: the ad set; CBO: the campaign) holding at least one
    qualifying ad. After a raise the chain is left alone for cfg.scale_up_wait_days full days
    (raised Thursday -> watch Friday and Saturday -> next raise Sunday at the earliest).
    """
    if cfg.scale_up_pct <= 0:
        return []

    def _cents(v) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    plans: Dict[str, Dict[str, Any]] = {}
    for d in decisions:
        if not d.adset_id or not raise_qualifies(d, cfg):
            continue
        info = adsets.get(d.adset_id) or {}
        if _cents(info.get("daily_budget")) > 0:
            eid, etype = d.adset_id, "adset"
        else:
            eid, etype = info.get("campaign_id") or "", "campaign"
            info = campaigns.get(eid) or {}
            if _cents(info.get("daily_budget")) <= 0:
                continue                           # lifetime budget or unknown -> not ours to raise
        if eid in plans:
            plans[eid]["ads"].append(d.name)
            continue
        last = last_raise.get(eid)
        if last and (today - last).days <= cfg.scale_up_wait_days:
            continue
        cur = _cents(info.get("daily_budget"))
        plans[eid] = {"id": eid, "type": etype, "name": info.get("name") or eid, "old_cents": cur,
                      "new_cents": int(round(cur * (1.0 + cfg.scale_up_pct / 100.0))),
                      "ads": [d.name], "cpa": round(d.cpa, 2), "sales": d.cpa_sales}
    return list(plans.values())


def _budget_raise_pass(graph, settings: Settings, decisions: List[AdDecision], *, dry_run: bool) -> int:
    """Fetch budgets + raise labels, plan today's raises, apply them.

    Like the cut pass, the wait guard is stateless on Meta: a raise stamps the budget owner
    with an "ADBOT_BUDGET_UP_<date>" label (added to its existing labels).
    """
    log = get_logger()
    cfg = settings.cpa
    if cfg.scale_up_pct <= 0 or not cfg.enabled:
        return 0
    acct = settings.meta.account_path
    adsets = {a["id"]: a for a in graph._get_all(
        f"{acct}/adsets", {"fields": "id,name,campaign_id,daily_budget,adlabels", "limit": 500})}
    campaigns = {c["id"]: c for c in graph._get_all(
        f"{acct}/campaigns", {"fields": "id,name,daily_budget,adlabels", "limit": 200})}
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    last_raise: Dict[str, dt.date] = {}
    for ent in list(adsets.values()) + list(campaigns.values()):
        for n in _label_names(ent):
            day = cpa.parse_date(n[len(RAISE_LABEL):]) if n.startswith(RAISE_LABEL) else None
            if day and (ent["id"] not in last_raise or day > last_raise[ent["id"]]):
                last_raise[ent["id"]] = day
    applied = 0
    for p in plan_budget_raises(decisions, adsets, campaigns, cfg, last_raise, today):
        tag = (f"{p['type']} {p['name']}  CPA={p['cpa']:.0f} ({p['sales']} sale) · "
               f"{', '.join(a[:30] for a in p['ads'])}")
        if dry_run:
            log.info("  [WOULD RAISE +%.0f%%] %s  RM%.2f -> RM%.2f /day", cfg.scale_up_pct, tag,
                     p["old_cents"] / 100, p["new_cents"] / 100)
            continue
        graph.update_daily_budget(p["id"], p["new_cents"])
        try:
            ent = adsets.get(p["id"]) or campaigns.get(p["id"]) or {}
            labels = ent.get("adlabels") or []
            if isinstance(labels, dict):
                labels = labels.get("data") or []
            keep = [l["id"] for l in labels if isinstance(l, dict) and l.get("id")]
            graph.set_ad_labels(p["id"], keep + [graph.get_or_create_label(acct, f"{RAISE_LABEL}{today.isoformat()}")])
        except Exception as exc:  # noqa: BLE001 — the raise stands; the next run could raise again
            log.warning("  !! could not label %s after the raise (%s) — wait guard weakened", p["id"], exc)
        state.append_pause_log(p["id"], p["type"], BUDGET_RAISE,
                               {"old_daily_myr": p["old_cents"] / 100.0, "new_daily_myr": p["new_cents"] / 100.0,
                                "cpa": p["cpa"], "sales": p["sales"], "ads": p["ads"]})
        log.info("  [RAISE +%.0f%%] %s  RM%.2f -> RM%.2f /day", cfg.scale_up_pct, tag,
                 p["old_cents"] / 100, p["new_cents"] / 100)
        applied += 1
    return applied


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


def _campaign_zero_lead_pass(graph, settings: Settings, *, dry_run: bool) -> int:
    """Pause whole CBO test campaigns that spent >= their campaign line with 0 registrations.

    Same lookback window as the ad rule. Only campaigns that (a) match an override entry
    carrying campaign_zero_lead_spend_myr and (b) hold the budget themselves (CBO) are judged;
    an ABO campaign is already covered ad by ad. Returns the number paused (or would-pause).
    """
    log = get_logger()
    account = settings.meta.account_path
    token = result_action_type(settings.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    preset, rng = cpl_window(settings, today)
    paused = 0
    for c in graph.list_campaigns(account):
        if c.get("effective_status") != "ACTIVE":
            continue
        name = c.get("name") or c["id"]
        line = campaign_zero_lead_line(settings.kpi, name)
        if line is None:
            continue
        info = graph.get_object(c["id"], "daily_budget,lifetime_budget") or {}
        if not (info.get("daily_budget") or info.get("lifetime_budget")):
            continue  # ABO: budget sits on the ad sets, the per-ad line handles it
        spend, results = parse_metrics(
            graph.get_ad_insight(c["id"], date_preset=preset, time_range=rng), token)
        if results > 0 or spend < line:
            log.info("  [campaign keep] %s  spend=%.2f results=%.0f (0-reg campaign line RM%.0f)",
                     name, spend, results, line)
            continue
        log.info("  [%s] %s  spend=%.2f with 0 results >= campaign line RM%.0f",
                 "WOULD PAUSE CAMPAIGN" if dry_run else "PAUSE CAMPAIGN", name, spend, line)
        if not dry_run:
            graph.update_status(c["id"], "PAUSED")
            state.append_pause_log(c["id"], "campaign", CAMPAIGN_ZERO_RESULTS,
                                   {"spend": round(spend, 2), "results": results, "line_myr": line})
        paused += 1
    return paused


def run(graph, settings: Settings, *, dry_run: bool = False) -> Dict[str, Any]:
    """Patrol the configured account plus meta.monitor_extra_accounts (operator: 「扩」)."""
    extras = []
    for a in settings.meta.monitor_extra_accounts or []:
        path = f"act_{str(a).replace('act_', '')}"
        if path and path != settings.meta.account_path and path not in extras:
            extras.append(path)
    if not extras:
        return _run_one(graph, settings, dry_run=dry_run)
    log = get_logger()
    totals: Dict[str, Any] = {"evaluated": 0, "paused": 0, "budget_cuts": 0, "budget_raises": 0, "campaign_pauses": 0,
                              "remaining": 0, "dry_run": dry_run, "accounts": {}}
    for path in [settings.meta.account_path] + extras:
        s2 = settings.model_copy(deep=True)
        s2.meta.ad_account_id = path
        log.info("═════════ monitor pass: %s ═════════", path)
        r = _run_one(graph, s2, dry_run=dry_run)
        totals["accounts"][path] = r
        for k in ("evaluated", "paused", "budget_cuts", "budget_raises", "campaign_pauses", "remaining"):
            totals[k] += int(r.get(k) or 0)
    return totals


def _run_one(graph, settings: Settings, *, dry_run: bool = False) -> Dict[str, Any]:
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
    raises = _budget_raise_pass(graph, settings, decisions, dry_run=dry_run)
    camp_paused = _campaign_zero_lead_pass(graph, settings, dry_run=dry_run)

    active_left = len([d for d in decisions if not d.should_pause])
    verb = "would pause" if dry_run else "paused"
    summary = (f"CPL monitor ({event}): evaluated {len(decisions)} active ads, "
               f"{verb} {len(to_pause) if dry_run else paused}, "
               f"{'would cut' if dry_run else 'cut'} {cuts} budget(s) -{settings.kpi.cpl_reduce_pct:.0f}%, "
               f"{'would raise' if dry_run else 'raised'} {raises} budget(s) +{settings.cpa.scale_up_pct:.0f}%, "
               f"{verb} {camp_paused} whole 0-reg campaign(s), "
               f"{active_left} remain (target CPL {settings.kpi.cpl_target_myr:.0f} MYR, "
               f"0-reg kill at {settings.kpi.cpl_min_spend_myr:.0f})")
    final_summary(log, summary)
    return {"evaluated": len(decisions), "paused": (len(to_pause) if dry_run else paused),
            "budget_cuts": cuts, "budget_raises": raises, "campaign_pauses": camp_paused, "remaining": active_left,
            "dry_run": dry_run}
