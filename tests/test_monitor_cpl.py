import math

import datetime as dt

from adbot import cpa
from adbot.monitor_cpl import (INSUFFICIENT_SPEND, MANUAL_HOLD, NO_RESULTS_YET, OVER_THRESHOLD,
                               WITHIN_THRESHOLD, ZERO_RESULTS, AdDecision, cpl_window, decide,
                               evaluate_account, extract_results, parse_metrics,
                               plan_budget_cuts, plan_budget_raises, result_action_type, sale_key, _week_start_thursday)
from adbot.settings import CpaCfg, KpiCfg, MetaCfg, Settings

KPI = KpiCfg(cpl_target_myr=40, cpl_threshold_myr=40, cpl_min_spend_myr=80,
             pause_zero_lead_after_spend=True)


def test_insufficient_spend_is_skipped():
    should, reason, cpl = decide(50, 0, KPI)
    assert not should and reason == INSUFFICIENT_SPEND and cpl is None


def test_zero_results_after_min_spend_pauses():
    should, reason, cpl = decide(100, 0, KPI)
    assert should and reason == ZERO_RESULTS and cpl == math.inf


def test_zero_results_kept_when_disabled():
    kpi = KpiCfg(cpl_target_myr=40, cpl_min_spend_myr=80, pause_zero_lead_after_spend=False)
    should, reason, _ = decide(100, 0, kpi)
    assert not should and reason == NO_RESULTS_YET


def test_cpl_over_target_is_flagged_but_never_pauses():
    # 11 Sep rules: high CPL with real leads gets a budget cut, not a kill.
    should, reason, cpl = decide(100, 1, KPI)
    assert not should and reason == OVER_THRESHOLD and round(cpl) == 100


def test_cpl_within_threshold_keeps():
    should, reason, cpl = decide(100, 4, KPI)
    assert not should and reason == WITHIN_THRESHOLD and cpl == 25


def test_result_action_type_is_exact_offsite_pixel_event():
    assert result_action_type("COMPLETE_REGISTRATION") == "offsite_conversion.fb_pixel_complete_registration"
    assert result_action_type("LEAD") == "offsite_conversion.fb_pixel_lead"


def test_extract_results_counts_only_the_exact_bucket():
    # Meta reports the SAME conversion under several overlapping buckets; only the exact
    # offsite-pixel one is Ads Manager "Results". Summing the rest 5x-overcounts (the bug).
    rat = result_action_type("COMPLETE_REGISTRATION")
    actions = [
        {"action_type": "offsite_conversion.fb_pixel_complete_registration", "value": "2"},
        {"action_type": "complete_registration", "value": "2"},
        {"action_type": "omni_complete_registration", "value": "2"},
        {"action_type": "offsite_complete_registration_add_meta_leads", "value": "2"},
        {"action_type": "offsite_complete_registration_add_20_s_calls", "value": "2"},
        {"action_type": "onsite_conversion.post_net_like", "value": "4"},
    ]
    assert extract_results(actions, rat) == 2


def test_parse_metrics_reads_spend_and_results():
    rat = result_action_type("COMPLETE_REGISTRATION")
    insight = {"spend": "120.50", "actions": [{"action_type": rat, "value": "2"},
                                              {"action_type": "complete_registration", "value": "2"}]}
    spend, results = parse_metrics(insight, rat)
    assert spend == 120.5 and results == 2


def test_parse_metrics_handles_empty():
    assert parse_metrics(None, "offsite_conversion.fb_pixel_complete_registration") == (0.0, 0.0)


# ── evaluate_account: whole-account scope, ad-level decisions, registration-only guard ──
class _FakeGraph:
    def __init__(self, campaigns, ads_by_campaign, insights):
        self._campaigns, self._ads, self._insights = campaigns, ads_by_campaign, insights

    def list_campaigns(self, account_path):
        return self._campaigns

    def list_ads_under_campaign(self, campaign_id):
        return self._ads.get(campaign_id, [])

    def get_ad_insight(self, ad_id, date_preset=None, time_range=None):
        return self._insights.get(ad_id)


def _ad(ad_id, status="ACTIVE", event="COMPLETE_REGISTRATION", created_time="2026-01-01", adset="s"):
    return {"id": ad_id, "name": ad_id, "effective_status": status, "created_time": created_time,
            "adset": {"name": adset, "promoted_object": {"custom_event_type": event} if event else {}}}


def _reg_insight(spend, results):
    rat = result_action_type("COMPLETE_REGISTRATION")
    return {"spend": str(spend), "actions": [{"action_type": rat, "value": str(results)}]}


def test_evaluate_account_is_whole_account_ad_level_and_registration_only():
    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"),
                        kpi=KpiCfg(cpl_target_myr=40, cpl_threshold_myr=40, cpl_min_spend_myr=80,
                                   cpl_lookback="last_3d", pause_zero_lead_after_spend=True))
    campaigns = [
        {"id": "A", "name": "MTC - Watches", "effective_status": "ACTIVE"},
        {"id": "B", "name": "STOCKBLOOM | Y", "effective_status": "PAUSED"},  # whole campaign off
    ]
    ads = {
        "A": [
            _ad("over"),                          # spend 100 / 1 reg -> CPL 100 -> flag, no pause
            _ad("within"),                        # spend 100 / 4 reg -> CPL 25 -> keep
            _ad("paused_ad", status="PAUSED"),    # not ACTIVE -> skipped
            _ad("purchase", event="PURCHASE"),    # wrong optimized event -> guard skips
            _ad("zero"),                          # spend 100 / 0 reg -> PAUSE (zero results)
        ],
        "B": [_ad("under_paused_campaign")],      # active ad but campaign paused -> skipped
    }
    insights = {"over": _reg_insight(100, 1), "within": _reg_insight(100, 4),
                "purchase": _reg_insight(100, 1), "zero": _reg_insight(100, 0),
                "under_paused_campaign": _reg_insight(100, 1)}

    decisions = evaluate_account(_FakeGraph(campaigns, ads, insights), settings)

    assert {d.name for d in decisions} == {"over", "within", "zero"}
    assert {d.name for d in decisions if d.should_pause} == {"zero"}
    assert {d.name: d.reason for d in decisions}["over"] == OVER_THRESHOLD


def test_evaluate_account_hold_list_exempts_over_ceiling_ad():
    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"),
                        kpi=KpiCfg(cpl_target_myr=40, cpl_threshold_myr=40, cpl_min_spend_myr=80,
                                   cpl_lookback="last_3d", pause_zero_lead_after_spend=True,
                                   cpl_hold=["街头突击"]))
    campaigns = [{"id": "A", "name": "MTC", "effective_status": "ACTIVE"}]
    ads = {"A": [_ad("Video 6：街头突击采访"), _ad("plain_zero")]}
    insights = {"Video 6：街头突击采访": _reg_insight(300, 0),  # 0 reg over line, but held
                "plain_zero": _reg_insight(100, 0)}            # 0 reg over line -> paused
    by_name = {d.name: d for d in evaluate_account(_FakeGraph(campaigns, ads, insights), settings)}

    assert by_name["Video 6：街头突击采访"].should_pause is False
    assert by_name["Video 6：街头突击采访"].reason == MANUAL_HOLD
    assert by_name["plain_zero"].should_pause is True


def test_week_to_date_cpl_window_from_thursday():
    # Jun 18 2026 is a Thursday; Jun 22 is the following Monday.
    assert _week_start_thursday(dt.date(2026, 6, 22)) == dt.date(2026, 6, 18)  # Mon -> prior Thu
    assert _week_start_thursday(dt.date(2026, 6, 18)) == dt.date(2026, 6, 18)  # Thu -> itself
    assert _week_start_thursday(dt.date(2026, 6, 24)) == dt.date(2026, 6, 18)  # Wed -> prior Thu
    s = Settings(kpi=KpiCfg(cpl_lookback="week_thu"))
    assert cpl_window(s, dt.date(2026, 6, 22)) == (None, {"since": "2026-06-18", "until": "2026-06-22"})
    assert cpl_window(Settings(kpi=KpiCfg(cpl_lookback="last_3d")), dt.date(2026, 6, 22)) == ("last_3d", None)


def test_evaluate_account_cpa_rescues_and_hard_stops():
    # CPA folded into the CPL decision (60-day window), via an injected context.
    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"),
                        kpi=KpiCfg(cpl_target_myr=40, cpl_threshold_myr=40, cpl_min_spend_myr=80,
                                   cpl_lookback="last_3d", pause_zero_lead_after_spend=True),
                        cpa=CpaCfg(enabled=True, hard_stop_myr=1200, conversion_days=14,
                                   min_spend_myr=1000))
    campaigns = [{"id": "A", "name": "MTC - News", "effective_status": "ACTIVE"}]
    ads = {"A": [_ad("rescue_me"), _ad("kill_me")]}
    insights = {"rescue_me": _reg_insight(300, 0),   # 0 reg past the kill line -> would pause
                "kill_me": _reg_insight(100, 4)}      # CPL 25 -> CPL keeps
    sold = {sale_key("MTC - News", "s", "rescue_me"): 10, sale_key("MTC - News", "s", "kill_me"): 2}  # this campaign's own sales
    spend60 = {"rescue_me": 7000.0, "kill_me": 4000.0}  # CPA 700 (rescue) / 2000 (hard stop)

    by_name = {d.name: d for d in evaluate_account(
        _FakeGraph(campaigns, ads, insights), settings, cpa_ctx=(sold, spend60))}

    assert by_name["rescue_me"].should_pause is False
    assert by_name["rescue_me"].reason == cpa.CPL_RESCUED          # 0-reg kill, but profitable name
    assert by_name["kill_me"].should_pause is True
    assert by_name["kill_me"].reason == cpa.HARD_STOP              # CPA>1200, matured -> pause


def test_plan_budget_cuts_daily_rules():
    kpi = KpiCfg(cpl_target_myr=95, cpl_reduce_pct=30, cpl_min_spend_myr=142.5)
    D = AdDecision
    decisions = [
        # set1 (ABO RM100): agg 300 spend / 2 reg -> CPL 150 > 95 -> cut to RM70
        D("a1", "a1", 200, 1, 200, False, OVER_THRESHOLD, adset_id="set1"),
        D("a2", "a2", 100, 1, 100, False, OVER_THRESHOLD, adset_id="set1"),
        # set2 (ABO RM100): CPL 50 -> no cut
        D("b1", "b1", 150, 3, 50, False, WITHIN_THRESHOLD, adset_id="set2"),
        # set3 (ABO RM60): over target but already at/below the RM50 floor path -> floored
        D("c1", "c1", 300, 2, 150, False, OVER_THRESHOLD, adset_id="set3"),
        # set4 (CBO -> campX RM200): folds to the campaign, CPL 160 -> cut to RM140
        D("d1", "d1", 320, 2, 160, False, OVER_THRESHOLD, adset_id="set4"),
        # set5: held ad in the set -> operator territory, never cut
        D("e1", "e1", 400, 2, 200, False, MANUAL_HOLD, adset_id="set5"),
        # set6: over target but already cut today -> skipped
        D("f1", "f1", 300, 2, 150, False, OVER_THRESHOLD, adset_id="set6"),
        # set7: under the verdict gate -> skipped
        D("g1", "g1", 100, 1, 100, False, INSUFFICIENT_SPEND, adset_id="set7"),
    ]
    adsets = {
        "set1": {"id": "set1", "name": "set1", "daily_budget": "10000", "campaign_id": "campA"},
        "set2": {"id": "set2", "name": "set2", "daily_budget": "10000", "campaign_id": "campA"},
        "set3": {"id": "set3", "name": "set3", "daily_budget": "6000", "campaign_id": "campA"},
        "set4": {"id": "set4", "name": "set4", "daily_budget": None, "campaign_id": "campX"},
        "set5": {"id": "set5", "name": "set5", "daily_budget": "10000", "campaign_id": "campA"},
        "set6": {"id": "set6", "name": "set6", "daily_budget": "10000", "campaign_id": "campA"},
        "set7": {"id": "set7", "name": "set7", "daily_budget": "10000", "campaign_id": "campA"},
    }
    campaigns = {"campA": {"id": "campA", "name": "campA", "daily_budget": None},
                 "campX": {"id": "campX", "name": "campX", "daily_budget": "20000"}}
    plans = {p["id"]: p for p in plan_budget_cuts(
        decisions, adsets, campaigns, kpi, 5000, {"set6": "2026-09-11"}, "2026-09-11")}

    assert set(plans) == {"set1", "set3", "campX"}
    assert plans["set1"]["new_cents"] == 7000 and not plans["set1"]["at_floor"]
    assert plans["set3"]["new_cents"] == 5000            # 60 * 0.7 = 42 -> floored at RM50
    assert plans["campX"]["type"] == "campaign" and plans["campX"]["new_cents"] == 14000


# ── 9 Oct: whole-campaign 0-registration line for CBO test campaigns ──────────
def test_campaign_zero_lead_line_reads_the_override_entry():
    from adbot.monitor_cpl import campaign_zero_lead_line
    kpi = KpiCfg(cpl_min_spend_overrides=[
        {"campaign_contains": "重测", "min_spend_myr": 80, "campaign_zero_lead_spend_myr": 150},
        {"campaign_contains": "线下", "min_spend_myr": 80},
    ])
    assert campaign_zero_lead_line(kpi, "[SG] x | 新片5支重测 | 1-1-5") == 150.0
    assert campaign_zero_lead_line(kpi, "[SG] x | 线下见证新片") is None   # entry without a campaign line
    assert campaign_zero_lead_line(kpi, "[SG] x | ordinary") is None


def test_campaign_zero_lead_pass_pauses_only_cbo_zero_result_campaigns(monkeypatch):
    from adbot import monitor_cpl

    class G:
        def __init__(self):
            self.paused = []

        def list_campaigns(self, account_path):
            return [
                {"id": "cbo_zero", "name": "A | 重测", "effective_status": "ACTIVE"},   # RM160 / 0 -> pause
                {"id": "cbo_lead", "name": "B | 重测", "effective_status": "ACTIVE"},   # RM160 / 1 -> keep
                {"id": "abo_zero", "name": "C | 重测", "effective_status": "ACTIVE"},   # ABO -> not judged here
                {"id": "cbo_under", "name": "D | 重测", "effective_status": "ACTIVE"},  # RM120 < 150 -> keep
                {"id": "cbo_other", "name": "E | normal", "effective_status": "ACTIVE"},  # no entry -> ignored
                {"id": "cbo_off", "name": "F | 重测", "effective_status": "PAUSED"},    # not active -> ignored
            ]

        def get_object(self, cid, fields):
            return {} if cid == "abo_zero" else {"daily_budget": "10000"}

        def get_ad_insight(self, cid, date_preset=None, time_range=None):
            return {"cbo_zero": _reg_insight(160, 0), "cbo_lead": _reg_insight(160, 1),
                    "abo_zero": _reg_insight(300, 0), "cbo_under": _reg_insight(120, 0),
                    "cbo_other": _reg_insight(500, 0), "cbo_off": _reg_insight(500, 0)}.get(cid)

        def update_status(self, cid, status):
            self.paused.append((cid, status))

    logged = []
    monkeypatch.setattr(monitor_cpl.state, "append_pause_log",
                        lambda eid, etype, reason, detail: logged.append((eid, etype, reason, detail)))
    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"),
                        kpi=KpiCfg(cpl_lookback="last_3d", cpl_min_spend_overrides=[
                            {"campaign_contains": "重测", "min_spend_myr": 80,
                             "campaign_zero_lead_spend_myr": 150}]))

    g = G()
    assert monitor_cpl._campaign_zero_lead_pass(g, settings, dry_run=True) == 1
    assert g.paused == [] and logged == []          # dry run writes nothing

    g = G()
    assert monitor_cpl._campaign_zero_lead_pass(g, settings, dry_run=False) == 1
    assert g.paused == [("cbo_zero", "PAUSED")]
    assert logged[0][:3] == ("cbo_zero", "campaign", monitor_cpl.CAMPAIGN_ZERO_RESULTS)
    assert logged[0][3]["line_myr"] == 150.0


# ── 19 Oct: CPL > 1.5x target with no sale -> pause; with a sale -> keep ─────────
def test_high_cpl_kill_only_without_sales():
    from adbot import monitor_cpl
    kpi = KpiCfg(cpl_target_myr=70, cpl_min_spend_myr=90, cpl_lookback="last_3d", high_cpl_kill_multiple=1.5)
    assert decide(120, 1, kpi)[:2] == (True, monitor_cpl.HIGH_CPL_NO_SALES)
    assert decide(100, 1, kpi)[:2] == (False, OVER_THRESHOLD)          # CPL 100 <= 105
    off = KpiCfg(cpl_target_myr=70, cpl_min_spend_myr=90, cpl_lookback="last_3d")
    assert decide(120, 1, off)[:2] == (False, OVER_THRESHOLD)          # disabled by default

    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"), kpi=kpi)
    settings.cpa.enabled = True
    campaigns = [{"id": "A", "name": "c", "effective_status": "ACTIVE"}]
    ads = {"A": [_ad("sold"), _ad("unsold")]}
    insights = {"sold": _reg_insight(150, 1), "unsold": _reg_insight(150, 1)}
    from adbot import cpa as _cpa
    ctx = ({sale_key("c", "s", "sold"): 1}, {"sold": 300.0, "unsold": 150.0})
    out = {d.name: d for d in evaluate_account(_FakeGraph(campaigns, ads, insights), settings, cpa_ctx=ctx)}
    assert out["unsold"].should_pause and out["unsold"].reason == monitor_cpl.HIGH_CPL_NO_SALES
    assert not out["sold"].should_pause and out["sold"].reason == monitor_cpl.HIGH_CPL_HAS_SALES


def test_sale_in_another_campaign_does_not_protect_a_new_copy():
    # 24 Oct: one old SG sale of a video kept every new copy of it alive past the RM90 line.
    from adbot import monitor_cpl
    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"),
                        kpi=KpiCfg(cpl_target_myr=70, cpl_min_spend_myr=90, cpl_lookback="last_3d",
                                   pause_zero_lead_after_spend=True, high_cpl_kill_multiple=1.5),
                        cpa=CpaCfg(enabled=True, hard_stop_myr=1200, conversion_days=14, min_spend_myr=1000))
    campaigns = [{"id": "N", "name": "[SG] 儿童长高方程式 | Health and Wellness | 老片重开 3 | 1-3-3",
                  "effective_status": "ACTIVE"}]
    ads = {"N": [_ad("Video: 孩子15岁以上还有机会长高吗？"), _ad("Video 5：Kaya 面包配 Milo")]}
    insights = {"Video: 孩子15岁以上还有机会长高吗？": _reg_insight(126, 0),   # 0 reg past RM90
                "Video 5：Kaya 面包配 Milo": _reg_insight(150, 1)}            # CPL 150 > 105
    old = "[sg] 儿童长高方程式 | health & wellness | 1-1-5"          # the sale's own (old) campaign
    sold = {sale_key(old, "s", "video: 孩子15岁以上还有机会长高吗？"): 1, sale_key(old, "s", "video 5:kaya 面包配 milo"): 1}
    spend60 = {"Video: 孩子15岁以上还有机会长高吗？": 190.0, "Video 5：Kaya 面包配 Milo": 150.0}
    out = {d.name: d for d in evaluate_account(_FakeGraph(campaigns, ads, insights), settings,
                                               cpa_ctx=(sold, spend60))}
    zero = out["Video: 孩子15岁以上还有机会长高吗？"]
    assert zero.should_pause and zero.reason == monitor_cpl.ZERO_RESULTS and zero.cpa_sales == 0
    high = out["Video 5：Kaya 面包配 Milo"]
    assert high.should_pause and high.reason == monitor_cpl.HIGH_CPL_NO_SALES

    # the same sale, carrying THIS campaign's UTM (punctuation/width differences folded), protects
    mine = {sale_key("[sg] 儿童长高方程式 | health and wellness | 老片重开 3 | 1-3-3", "s",
                     "video: 孩子15岁以上还有机会长高吗？"): 1}
    out = {d.name: d for d in evaluate_account(_FakeGraph(campaigns, ads, insights), settings,
                                               cpa_ctx=(mine, spend60))}
    assert not out["Video: 孩子15岁以上还有机会长高吗？"].should_pause
    assert out["Video: 孩子15岁以上还有机会长高吗？"].reason == cpa.CPL_RESCUED


def test_sale_in_another_ad_set_does_not_protect():
    # 29 Oct operator: the sale must carry this ad's own campaign, ad set AND ad.
    from adbot import monitor_cpl
    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"),
                        kpi=KpiCfg(cpl_target_myr=70, cpl_min_spend_myr=90, cpl_lookback="last_3d",
                                   pause_zero_lead_after_spend=True),
                        cpa=CpaCfg(enabled=True, hard_stop_myr=1300, conversion_days=14, min_spend_myr=1000))
    campaigns = [{"id": "C", "name": "c", "effective_status": "ACTIVE"}]
    ads = {"C": [_ad("v", adset="Interest: Family and Relationships")]}
    insights = {"v": _reg_insight(95, 0)}
    other = {sale_key("c", "Interest: Food and Drink + Milk", "v"): 1}
    out = evaluate_account(_FakeGraph(campaigns, ads, insights), settings, cpa_ctx=(other, {"v": 95.0}))[0]
    assert out.should_pause and out.reason == monitor_cpl.ZERO_RESULTS
    own = {sale_key("c", "interest:family and relationships", "v"): 1}
    out = evaluate_account(_FakeGraph(campaigns, ads, insights), settings, cpa_ctx=(own, {"v": 95.0}))[0]
    assert not out.should_pause and out.reason == cpa.CPL_RESCUED


def test_hard_stop_exemption_skips_only_the_cpa_line():
    # 24 Oct operator 「重开」: Video 5 kept past the CPA hard stop; the RM90 zero-reg line still applies.
    from adbot import monitor_cpl
    settings = Settings(meta=MetaCfg(conversion_event="COMPLETE_REGISTRATION"),
                        kpi=KpiCfg(cpl_target_myr=70, cpl_min_spend_myr=90, cpl_lookback="last_3d",
                                   pause_zero_lead_after_spend=True),
                        cpa=CpaCfg(enabled=True, hard_stop_myr=1200, conversion_days=14, min_spend_myr=1000,
                                   hard_stop_exempt_ad_ids=["keep_me", "dry"]))
    campaigns = [{"id": "A", "name": "c", "effective_status": "ACTIVE"}]
    ads = {"A": [_ad("keep_me"), _ad("other"), _ad("dry")]}
    insights = {"keep_me": _reg_insight(420, 8), "other": _reg_insight(420, 8), "dry": _reg_insight(120, 0)}
    sold = {sale_key("c", "s", "keep_me"): 1, sale_key("c", "s", "other"): 1, sale_key("c", "s", "dry"): 1}
    spend60 = {"keep_me": 2112.0, "other": 2112.0, "dry": 2112.0}
    out = {d.name: d for d in evaluate_account(_FakeGraph(campaigns, ads, insights), settings,
                                               cpa_ctx=(sold, spend60))}
    assert not out["keep_me"].should_pause and out["keep_me"].reason == monitor_cpl.HARD_STOP_EXEMPT
    assert out["other"].should_pause and out["other"].reason == cpa.HARD_STOP
    assert out["dry"].should_pause and out["dry"].reason == monitor_cpl.ZERO_RESULTS


# ── 29 Oct operator 「加 20%」「A」: raise on CPA within target ─────────────────────
def test_plan_budget_raises():
    cfg = CpaCfg(enabled=True, target_myr=740, conversion_days=14, min_spend_myr=1000,
                 scale_up_pct=20, scale_up_wait_days=2)
    D = AdDecision
    good = dict(cpa=700.0, cpa_sales=3, age_days=30, cpa_spend=2100.0)
    decisions = [
        D("a", "a", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s1", **good),           # ABO -> raise s1
        D("b", "b", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s2", **good),           # CBO -> raise campX
        D("b2", "b2", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s2b", **good),        # same campaign: once
        D("c", "c", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s3", **dict(good, cpa=800.0)),     # over target
        D("d", "d", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s4", **dict(good, age_days=3)),    # new ad: no age gate
        D("e", "e", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s5", **dict(good, cpa_sales=1, cpa=300.0, cpa_spend=300.0)),  # 1 sale, RM300: raise
        D("f", "f", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s6", **good),           # raised 2 days ago -> wait
        D("g", "g", 50, 1, 50, False, WITHIN_THRESHOLD, adset_id="s7", **good),           # raised 3 days ago -> raise
        D("h", "h", 95, 0, math.inf, True, ZERO_RESULTS, adset_id="s8", **good),          # being paused
    ]
    adsets = {k: {"id": k, "name": k, "daily_budget": "5000", "campaign_id": "campA"}
              for k in ("s1", "s3", "s4", "s5", "s6", "s7", "s8")}
    adsets["s2"] = {"id": "s2", "name": "s2", "daily_budget": None, "campaign_id": "campX"}
    adsets["s2b"] = {"id": "s2b", "name": "s2b", "daily_budget": None, "campaign_id": "campX"}
    campaigns = {"campX": {"id": "campX", "name": "campX", "daily_budget": "10000"}}
    today = dt.date(2026, 10, 29)
    plans = {p["id"]: p for p in plan_budget_raises(
        decisions, adsets, campaigns, cfg, {"s6": dt.date(2026, 10, 27), "s7": dt.date(2026, 10, 26)}, today)}
    assert set(plans) == {"s1", "campX", "s4", "s5", "s7"}
    assert plans["s1"]["new_cents"] == 6000
    assert plans["campX"]["type"] == "campaign" and plans["campX"]["new_cents"] == 12000
    assert plans["campX"]["ads"] == ["b", "b2"]
    assert plan_budget_raises(decisions, adsets, campaigns, CpaCfg(scale_up_pct=0), {}, today) == []


# ── 29 Oct operator: a campaign is never left ON with no live ad ──────────────────
def test_close_empty_campaigns(monkeypatch):
    from adbot import monitor_cpl

    class G:
        def __init__(self):
            self.paused = []

        def list_ads_under_campaign(self, cid):
            return {"empty": [{"id": "x", "effective_status": "ACTIVE"}, {"id": "y", "effective_status": "PAUSED"}],
                    "busy": [{"id": "z", "effective_status": "ACTIVE"}, {"id": "w", "effective_status": "ACTIVE"}]}[cid]

        def update_status(self, eid, status):
            self.paused.append((eid, status))

    monkeypatch.setattr(monitor_cpl.state, "append_pause_log", lambda *a, **k: None)
    g = G()
    assert monitor_cpl.close_empty_campaigns(g, ["empty", "busy"], ["x", "z"], dry_run=True) == ["empty"]
    assert g.paused == []
    assert monitor_cpl.close_empty_campaigns(g, ["empty", "busy"], ["x", "z"], dry_run=False) == ["empty"]
    assert g.paused == [("empty", "PAUSED")]


def test_raise_needs_a_recent_registration():
    # 30 Oct operator 「B」: no raise unless >= 1 registration in the last 2 days
    cfg = CpaCfg(enabled=True, target_myr=740, scale_up_pct=20, scale_up_wait_days=2,
                 scale_up_recent_days=2, scale_up_min_recent_results=1)
    D = AdDecision
    good = dict(cpa=600.0, cpa_sales=1, age_days=30, cpa_spend=600.0)
    decisions = [D("quiet", "quiet", 168, 0, None, False, INSUFFICIENT_SPEND, adset_id="s1", **good),
                 D("busy", "busy", 100, 1, 100, False, WITHIN_THRESHOLD, adset_id="s2", **good)]
    adsets = {k: {"id": k, "name": k, "daily_budget": "5000", "campaign_id": "c"} for k in ("s1", "s2")}
    plans = plan_budget_raises(decisions, adsets, {}, cfg, {}, dt.date(2026, 10, 30), {"quiet": 0.0, "busy": 1.0})
    assert [p["id"] for p in plans] == ["s2"]
