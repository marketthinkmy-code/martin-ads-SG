"""Where the money went vs where the paying students came from. Read-only.

THE QUESTION
------------
"Recent leads feel like a quality problem — compare the leads that actually PAID against which
ads spent the most, and tell me whether the ads that used to make money were starved of budget."

Those are three different questions and they need different evidence, so this reports all three
rather than one number:

  1. LEAD QUALITY.  A cheap registration that never buys is more expensive than a dear one that
     does. So every ad gets a lead→paid conversion rate, not just a CPL. An ad whose CPL beats
     the account average while its lead→paid rate is far below it IS the lead-quality problem —
     it is buying the cheapest, least interested registrations available.
  2. WHERE THE MONEY WENT.  Last-30d spend ranked, each line carrying what that ad has ever
     produced. Money sitting on ads with no sales history is the waste, and it is only visible
     when spend and lifetime outcome sit on the same row.
  3. STARVED WINNERS.  The operator's actual hypothesis. An ad with real lifetime sales at a CPA
     inside target, receiving little or no recent budget, is money left on the table. This is the
     inverse of (2) and the two are quantified against each other at the end.

WHY LIFETIME CPA AGAINST 30-DAY SPEND
-------------------------------------
"Ads that used to make money" is a lifetime claim; "did not get enough budget" is a recent one.
Judging both on the same recent window would hide exactly the case being asked about — an ad that
earned its reputation months ago and has been dark since. So proven-ness is measured over
lifetime and funding over 30 days, deliberately.

MATCHING, AND WHERE IT CAN LIE
------------------------------
Sales carry the ad NAME as a UTM string; Meta carries its own ad names. They are joined on
cpa.ad_key (width/punctuation/case-insensitive), exact first, then substring. Two consequences
are reported rather than hidden:

  · Renaming an ad in Ads Manager breaks the join for every sale recorded under the old name.
    This account renames ads, so the unmatched lists below are a live risk, not a formality.
  · A sheet row whose UTM is blank or hand-typed cannot match anything. Unmatched sales are
    counted and shown, because a large unmatched pile would mean the whole ranking is unreliable
    and that has to be visible before anyone acts on it.

Spend is aggregated per ad NAME KEY, not per ad id, so one creative running as several ads across
campaigns is judged as one creative — which is how creative decisions are actually made.

PROVABLY-SG SALES ONLY
----------------------
The Paid Student List is shared across markets, and the same creative names run in the MY account.
The first run of this audit joined on ad name alone and produced lead→paid rates above 100% —
more buyers than this account ever had leads — because MY buyers were being credited to SG spend.
So every judgement below counts only provably-SG sales, the account's own attribution standard
(UTM campaign contains '[sg]' / 'martin-sg' / 'martin sg', as in keep_or_pause_high_cpl.py).
The all-market count is still shown per row as context, because a creative with many MY sales and
no SG ones is a different situation from a creative with no sales anywhere.

Read-only: this creates, changes and pauses nothing.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

RECENT_DAYS = 30
TOP_N = 18


def money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v == math.inf:
        return "∞"
    return f"{v:,.0f}"


def pct(n: float, d: float) -> str:
    return "—" if d <= 0 else f"{100.0 * n / d:.1f}%"


def collect(rows: List[Dict[str, Any]], token: str) -> Dict[str, Dict[str, Any]]:
    """ad_key(name) -> {name, spend, leads} for one insights window.

    Keyed by name rather than id so the same creative running in several campaigns is treated as
    one creative; that is the unit a budget decision is actually made on.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        name = r.get("ad_name") or ""
        if not name:
            continue
        k = cpa.ad_key(name)
        try:
            spend = float(r.get("spend", 0) or 0)
        except (TypeError, ValueError):
            spend = 0.0
        rec = out.setdefault(k, {"name": name, "spend": 0.0, "leads": 0.0})
        rec["spend"] += spend
        rec["leads"] += extract_results(r.get("actions"), token)
    return out


def match_sales(sale_keys: Dict[str, int], meta_keys: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """Map each sheet ad-key to a Meta ad-key. Exact first, then unique substring.

    Substring is a fallback, not the default: 'video8' would otherwise match both 'video8' and
    'video80'. A substring hit is only accepted when exactly ONE Meta key contains it, so an
    ambiguous name is reported unmatched instead of being attributed to a guess.
    """
    meta_set = set(meta_keys)
    mapping: Dict[str, str] = {}
    unmatched: List[str] = []
    for sk in sale_keys:
        if not sk:
            unmatched.append(sk)
            continue
        if sk in meta_set:
            mapping[sk] = sk
            continue
        hits = [mk for mk in meta_keys if sk in mk or mk in sk]
        if len(hits) == 1:
            mapping[sk] = hits[0]
        else:
            unmatched.append(sk)
    return mapping, unmatched


def sg_sale(campaign_norm: str) -> bool:
    """Provably-SG sale — the account's own attribution standard (keep_or_pause_high_cpl.py).

    Campaign values from parse_sales are already casefolded by cpa.norm, so plain substring
    checks are enough. MY-shared-name sales never count for an SG judgement — in either
    direction: not to keep an ad alive, and not to kill one.
    """
    c = campaign_norm or ""
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()          # MYT/SGT
    since = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
    token = result_action_type(s.meta.conversion_event)
    target = s.cpa.target_myr
    hard = s.cpa.hard_stop_myr

    # ── sales ────────────────────────────────────────────────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _cols, _hdr = cpa.parse_sales(values, s.cpa.price_myr)
    log.info("paid list: %d sale row(s) parsed from %r", len(sales), s.cpa.sales_tab)

    by_month: Dict[str, int] = defaultdict(int)
    for sale in sales:
        by_month[sale.date.strftime("%Y-%m") if sale.date else "no date"] += 1
    log.info("   sales by month: %s",
             "  ".join(f"{k}:{v}" for k, v in sorted(by_month.items())))

    sale_count: Dict[str, int] = defaultdict(int)       # all markets — context only
    sale_sg: Dict[str, int] = defaultdict(int)          # provably-SG — every judgement uses this
    sale_value: Dict[str, float] = defaultdict(float)
    sale_recent: Dict[str, int] = defaultdict(int)
    n_sg = 0
    for sale in sales:
        k = cpa.ad_key(sale.ad)
        sale_count[k] += 1
        if sg_sale(sale.campaign):
            n_sg += 1
            sale_sg[k] += 1
            sale_value[k] += sale.amount
            if sale.date and sale.date > today - dt.timedelta(days=RECENT_DAYS):
                sale_recent[k] += 1
    log.info("   provably-SG (UTM campaign carries the SG marker): %d of %d rows", n_sg, len(sales))

    # ── spend ────────────────────────────────────────────────────────────────────
    g = graph_client(s)
    acct = s.meta.account_path
    fields = "ad_name,spend,actions"
    life = collect(g.account_insights(acct, level="ad", fields=fields, date_preset="maximum"),
                   token)
    recent = collect(g.account_insights(acct, level="ad", fields=fields,
                                        time_range={"since": since, "until": today.isoformat()}),
                     token)
    log.info("meta: %d creative(s) lifetime · %d with spend in the last %dd",
             len(life), sum(1 for v in recent.values() if v["spend"] > 0), RECENT_DAYS)

    mapping, unmatched = match_sales(sale_count, list(life.keys()))
    matched_sales = sum(sale_sg[k] for k in mapping)          # SG lane — the account line
    lost_sales = sum(sale_sg[k] for k in unmatched)           # SG sales the join loses

    # Fold sheet keys onto their Meta key so one creative carries all of its sales.
    paid: Dict[str, int] = defaultdict(int)             # provably-SG
    paid_all: Dict[str, int] = defaultdict(int)         # all markets, context only
    paid_recent: Dict[str, int] = defaultdict(int)
    revenue: Dict[str, float] = defaultdict(float)
    for sk, mk in mapping.items():
        paid[mk] += sale_sg[sk]
        paid_all[mk] += sale_count[sk]
        paid_recent[mk] += sale_recent[sk]
        revenue[mk] += sale_value[sk]

    # ── per-creative rows ────────────────────────────────────────────────────────
    rows = []
    for k, l in life.items():
        r30 = recent.get(k, {"spend": 0.0, "leads": 0.0})
        n_paid = paid.get(k, 0)
        rows.append({
            "key": k, "name": l["name"],
            "life_spend": l["spend"], "life_leads": l["leads"],
            "spend30": r30["spend"], "leads30": r30["leads"],
            "paid": n_paid, "paid_all": paid_all.get(k, 0),
            "paid30": paid_recent.get(k, 0), "revenue": revenue.get(k, 0.0),
            "cpa": cpa.cpa(l["spend"], n_paid),
            "cpl30": (r30["spend"] / r30["leads"]) if r30["leads"] else None,
            "l2p": (n_paid / l["leads"]) if l["leads"] else None,
        })

    tot30 = sum(r["spend30"] for r in rows)
    leads30 = sum(r["leads30"] for r in rows)
    life_spend = sum(r["life_spend"] for r in rows)
    life_leads = sum(r["life_leads"] for r in rows)
    acct_l2p = (matched_sales / life_leads) if life_leads else 0.0

    log.info("═" * 108)
    log.info("ACCOUNT — lifetime spend RM%s · %s leads · %d matched provably-SG sales · "
             "lead→paid %s", money(life_spend), money(life_leads), matched_sales,
             pct(matched_sales, life_leads))
    log.info("          last %dd  spend RM%s · %s leads · blended CPL RM%s",
             RECENT_DAYS, money(tot30), money(leads30),
             money(tot30 / leads30) if leads30 else None)
    if lost_sales:
        log.info("          ‼ %d provably-SG sale(s) could NOT be matched to any Meta ad — every "
                 "ranking below is missing them (renamed ads / blank UTM)", lost_sales)

    # ── 1) where the money went ──────────────────────────────────────────────────
    log.info("═" * 108)
    log.info("1) WHERE THE MONEY WENT — top %d by last-%dd spend", TOP_N, RECENT_DAYS)
    log.info("   %-38s %9s %7s %8s %9s %8s %8s", "creative", f"{RECENT_DAYS}d spend",
             "leads", "CPL", "paid(life)", "CPA", "lead→paid")
    burn_no_sales = 0.0
    for r in sorted(rows, key=lambda x: -x["spend30"])[:TOP_N]:
        if r["spend30"] <= 0:
            continue
        # Two different failures, and they need different fixes, so they are labelled apart:
        # spending with no sale in the account's whole history, versus selling but above the
        # price at which a sale still pays for itself.
        if r["paid"] == 0 and r["paid_all"] == 0:
            flag = "  ← never sold, any market"
        elif r["paid"] == 0:
            flag = f"  ← no SG sale ({r['paid_all']} elsewhere)"
        elif r["cpa"] != math.inf and r["cpa"] > hard:
            flag = "  ← above hard stop"
        else:
            flag = ""
        log.info("   %-38s %9s %7s %8s %9d %8s %8s%s", r["name"][:38], money(r["spend30"]),
                 money(r["leads30"]), money(r["cpl30"]), r["paid"], money(r["cpa"]),
                 pct(r["paid"], r["life_leads"]), flag)
    for r in rows:
        if r["spend30"] > 0 and r["paid"] == 0:
            burn_no_sales += r["spend30"]     # no provably-SG sale ever

    # ── 2) proven winners and what they are being paid ───────────────────────────
    log.info("═" * 108)
    log.info("2) PROVEN WINNERS — provably-SG lifetime sales, ranked by CPA (best first)")
    log.info("   %-38s %6s %6s %9s %10s %11s %9s", "creative", "SG", "all", "CPA", "lifetime",
             f"{RECENT_DAYS}d spend", "share")
    winners = sorted([r for r in rows if r["paid"] > 0], key=lambda x: x["cpa"])
    starved: List[Dict[str, Any]] = []
    for r in winners[:TOP_N]:
        share = pct(r["spend30"], tot30)
        flag = ""
        if r["cpa"] <= target and r["spend30"] < tot30 * 0.02:
            flag = "  ← STARVED"
            starved.append(r)
        log.info("   %-38s %6d %6d %9s %10s %11s %9s%s", r["name"][:38], r["paid"],
                 r["paid_all"], money(r["cpa"]), money(r["life_spend"]), money(r["spend30"]),
                 share, flag)

    # ── 3) lead quality: cheap leads that never buy ──────────────────────────────
    log.info("═" * 108)
    log.info("3) LEAD QUALITY — cheap registrations that do not convert (account avg lead→paid %s)",
             pct(matched_sales, life_leads))
    log.info("   %-38s %9s %8s %8s %9s %8s", "creative", f"{RECENT_DAYS}d spend", "leads",
             "CPL", "lead→paid", "verdict")
    suspects = []
    for r in sorted(rows, key=lambda x: -x["spend30"]):
        if r["spend30"] <= 0 or r["life_leads"] < 5:
            continue
        rate = r["l2p"] or 0.0
        cheap = r["cpl30"] is not None and r["cpl30"] <= s.kpi.cpl_threshold_myr
        if cheap and rate < acct_l2p * 0.5:
            suspects.append(r)
            log.info("   %-38s %9s %8s %8s %9s %8s", r["name"][:38], money(r["spend30"]),
                     money(r["life_leads"]), money(r["cpl30"]), pct(r["paid"], r["life_leads"]),
                     "cheap leads, no buyers")

    # ── 4) the arithmetic ────────────────────────────────────────────────────────
    log.info("═" * 108)
    best = winners[0] if winners else None
    starved_spend = sum(r["spend30"] for r in starved)
    parts: List[str] = []
    parts.append(f"Last {RECENT_DAYS}d: RM{money(tot30)} spent for {money(leads30)} registrations "
                 f"(blended CPL RM{money(tot30 / leads30) if leads30 else 0}).")
    if tot30 > 0:
        parts.append(f"RM{money(burn_no_sales)} of that ({pct(burn_no_sales, tot30)}) went to "
                     f"creatives with NO provably-SG paid student in this account's whole history "
                     f"— that is the single biggest lever here, and it is a targeting and "
                     f"creative problem, not a bidding one.")
    if starved:
        names = ", ".join(r["name"][:26] for r in starved[:4])
        parts.append(f"{len(starved)} creative(s) with a proven CPA at or under the RM{target:,.0f} "
                     f"target are taking under 2% of budget each ({names}) — RM{money(starved_spend)} "
                     f"combined. That is the operator's hypothesis and it is supported: money is on "
                     f"unproven creatives while proven ones sit idle.")
    else:
        parts.append(f"No proven-CPA creative is starved right now: every creative with a lifetime "
                     f"CPA at or under RM{target:,.0f} is already carrying a meaningful share of "
                     f"budget, so under-funding proven winners is NOT what is going wrong.")
    if best and best["cpa"] and best["cpa"] != math.inf and burn_no_sales > 0:
        could = burn_no_sales / best["cpa"]
        parts.append(f"For scale: the RM{money(burn_no_sales)} on zero-sale creatives is about "
                     f"{could:.1f} extra paid students at the best proven CPA "
                     f"(RM{money(best['cpa'])}, {best['name'][:30]}) — an upper bound, since CPA "
                     f"rises as a winner is pushed harder.")
    if suspects:
        parts.append(f"{len(suspects)} creative(s) buy registrations UNDER the RM"
                     f"{s.kpi.cpl_threshold_myr:,.0f} CPL ceiling but convert to paid at less than half "
                     f"the account rate — those are the lead-quality problem by name, and a CPL "
                     f"guardrail alone will never catch them because they look cheap.")
    if lost_sales:
        parts.append(f"CAVEAT: {lost_sales} of {n_sg} provably-SG sales carry a UTM that matches no "
                     f"current Meta ad name (renamed ads or blank UTM), so every figure above "
                     f"understates somebody. Fix that before treating the ranking as final.")
    final_summary(log, " ".join(parts))


if __name__ == "__main__":
    main()
