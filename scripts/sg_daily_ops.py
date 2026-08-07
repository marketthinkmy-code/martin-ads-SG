"""SG daily ops — Martin SG ad account (act_1024930575770087, MYR). LIVE writes (Section D only).

One run covers the daily routine end to end:

  A. Yesterday's provably-SG paid sales — which ads sold (SG only).
  B. Reopened-winner status — 6 operator-named winners: spend + SG sales since reopen/scale/trim.
  C. New-test bucket status — 5 buckets (exact ad_ids from state/), last_3d spend + 30d SG sales.
  D. Backstop pause — ACTIVE reg-optimized ads that are ALL FOUR of:
       age >= 14d · 30d spend >= RM300 · 0 provably-SG 30d sales · 30d CPL > RM65
     get PAUSED (flips only the ad, never its ad set/campaign; Scale-Winners campaign is
     skipped entirely). Idempotent — only ever acts on currently-ACTIVE ads.

Provably-SG sale = UTM campaign contains '[sg]' / 'martin-sg' / 'martin sg' — the account's
own SG-attribution standard (see keep_or_pause_high_cpl.py), so MY-shared-name sales never
count as a reason to keep an SG ad alive, and never count as a reason to kill one either.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ad_key = cpa.ad_key

NAMED_WINNERS = [
    ("新马版牛奶迷思 V8-1", "新马版主打牛奶迷思"),
    ("担心孩子的高度 Hook7", "担心孩子的高度"),
    ("准备早餐面包 Hook3", "准备早餐面包"),
    ("dec hook 13", "花了几千块"),
    ("孩子15岁以上", "孩子15岁以上"),
    ("我不会买牛奶 MAR V1", "我不会买牛奶"),
]

# label -> ad_ids, sourced from state/entities_*.json (exact build records, no name-guessing)
NEW_TEST_BUCKETS = [
    ("Parents 兴趣定向 1-1-4 (V11/13/14/15)",
     ["120256891853620093", "120256891856130093", "120256894654280093", "120256899218410093"]),
    ("Parents 1-1-2 (V7/16)",
     ["120256980920770093", "120256980922330093"]),
    ("Family & Relationships 1-1-3 ×2 (batch A: V15/16/7)",
     ["120256985979690093", "120256985982080093", "120256985983240093"]),
    ("Family & Relationships 1-1-3 ×2 (batch B: V11/13/14)",
     ["120256985985130093", "120256985986040093", "120256985986730093"]),
    ("Health & Wellness 1-1-5",
     ["120256984987610093", "120256984987760093", "120256984987970093",
      "120256984988360093", "120256984988770093"]),
    ("Milk & Bread 1-1-5",
     ["120256984990200093", "120256984990530093", "120256984991060093",
      "120256984991390093", "120256984991820093"]),
]

CPL_CEIL = 65.0
MIN_SPEND_30D = 300.0
MIN_AGE_DAYS = 14


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    return "—" if v is None else ("∞" if v == math.inf else f"{v:.0f}")


def _sgsale(campaign_norm: str) -> bool:
    c = campaign_norm or ""
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def _is_scalewinners(name: str) -> bool:
    c = (name or "").lower()
    return "scale-winners" in c or "scale winners" in c


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    yday = today - dt.timedelta(days=1)
    d30 = today - dt.timedelta(days=30)
    reg_token = result_action_type(s.meta.conversion_event)
    want_event = (s.meta.conversion_event or "").upper()

    # ── paid sales: provably-SG only, keyed by ad NAME ──────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    yday_sg_rows = []
    sg30 = defaultdict(int)
    disp_name = {}
    for x in sales:
        if not x.ad or not x.date:
            continue
        sg = _sgsale(x.campaign)
        k = ad_key(x.ad)
        disp_name.setdefault(k, x.ad)
        if sg and x.date == yday:
            yday_sg_rows.append(x.ad)
        if sg and x.date > d30:
            sg30[k] += 1

    print("=" * 100)
    print(f"SECTION A · Yesterday ({yday}) provably-SG paid sales")
    print("=" * 100)
    if yday_sg_rows:
        cnt = defaultdict(int)
        for ad in yday_sg_rows:
            cnt[ad] += 1
        for ad, n in sorted(cnt.items(), key=lambda kv: -kv[1]):
            print(f"  ✅ {n}x  {ad}")
        print(f"Total SG sales yesterday: {len(yday_sg_rows)}")
    else:
        print("  (no provably-SG sale dated yesterday)")

    # ── whole-account ad pull (name/status/age/campaign) ────────────────────────
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,created_time,"
                  "campaign{id,name,effective_status},adset{id,name,promoted_object,effective_status}",
        "limit": 500})
    ad_by_id = {a["id"]: a for a in ads}
    sp30 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend",
        time_range={"since": d30.isoformat(), "until": today.isoformat()})}
    reg30 = {r.get("ad_id"): extract_results(r.get("actions"), reg_token) for r in g.account_insights(
        acct, level="ad", fields="ad_id,actions",
        time_range={"since": d30.isoformat(), "until": today.isoformat()})}
    sp3 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", date_preset="last_3d")}

    # ── SECTION B · named reopened-winner status ────────────────────────────────
    print()
    print("=" * 100)
    print("SECTION B · Reopened-winner status (30d spend / 30d SG sales)")
    print("=" * 100)
    for label, core in NAMED_WINNERS:
        ck = ad_key(core)
        matches = [a for a in ads if ck in ad_key(a.get("name", ""))]
        if not matches:
            print(f"  ❓ {label}: NOT FOUND")
            continue
        tot_sp30 = sum(sp30.get(a["id"], 0.0) for a in matches)
        tot_sg = sum(v for k2, v in sg30.items() if ck in k2)  # substring match: core phrase inside the full sheet ad-name key
        live = sum(1 for a in matches if a.get("status") == "ACTIVE")
        statuses = ", ".join(f"{a['id'][-6:]}={a.get('status')}" for a in matches)
        print(f"  {label}: {len(matches)} copy(ies), {live} ACTIVE · 30d spend RM{tot_sp30:.0f} · "
              f"30d SG sales {tot_sg} · [{statuses}]")

    # ── SECTION C · new-test bucket status ──────────────────────────────────────
    print()
    print("=" * 100)
    print("SECTION C · New-test bucket status (last_3d spend · 30d SG sales)")
    print("=" * 100)
    for label, ids in NEW_TEST_BUCKETS:
        tot_sp3 = sum(sp3.get(i, 0.0) for i in ids)
        tot_sp30 = sum(sp30.get(i, 0.0) for i in ids)
        names = [ad_by_id.get(i, {}).get("name", i) for i in ids]
        tot_sg = sum(sg30.get(ad_key(n), 0) for n in names)
        live = sum(1 for i in ids if ad_by_id.get(i, {}).get("status") == "ACTIVE")
        print(f"  {label}: {len(ids)} ad(s), {live} ACTIVE · last_3d spend RM{tot_sp3:.0f} · "
              f"30d spend RM{tot_sp30:.0f} · 30d SG sales {tot_sg}")
        for i in ids:
            a = ad_by_id.get(i, {})
            print(f"      · {a.get('name', i)[:50]:50} status={a.get('status','?'):8} "
                  f"3d=RM{sp3.get(i,0):.0f} 30d=RM{sp30.get(i,0):.0f}")

    # ── SECTION D · backstop pause ───────────────────────────────────────────────
    print()
    print("=" * 100)
    print(f"SECTION D · Backstop pause — age>={MIN_AGE_DAYS}d · 30d spend>=RM{MIN_SPEND_30D:.0f} · "
          f"0 SG 30d sales · 30d CPL>RM{CPL_CEIL:.0f}")
    print("=" * 100)
    paused_rows = []
    for a in ads:
        if a.get("effective_status") != "ACTIVE" or a.get("status") != "ACTIVE":
            continue
        promoted = (a.get("adset") or {}).get("promoted_object") or {}
        if (promoted.get("custom_event_type") or "").upper() != want_event:
            continue
        camp = a.get("campaign") or {}
        if _is_scalewinners(camp.get("name", "")):
            continue
        aid, name = a["id"], a.get("name", a["id"])
        created = cpa.parse_date((a.get("created_time") or "")[:10])
        age = (today - created).days if created else None
        spend30 = sp30.get(aid, 0.0)
        results30 = reg30.get(aid, 0.0)
        cpl30 = (spend30 / results30) if results30 > 0 else (math.inf if spend30 > 0 else None)
        sgsold30 = sg30.get(ad_key(name), 0)

        if age is None or age < MIN_AGE_DAYS:
            continue  # too new — sales lag
        if spend30 < MIN_SPEND_30D:
            continue  # not enough spend to judge
        if sgsold30 > 0:
            continue  # real SG sale — never touch
        if cpl30 is None or cpl30 == math.inf:
            cpl_over = spend30 > 0  # spent with 0 registrations at all -> effectively infinite CPL
        else:
            cpl_over = cpl30 > CPL_CEIL
        if not cpl_over:
            continue

        g.update_status(aid, "PAUSED")
        paused_rows.append({"name": name, "age": age, "sp30": spend30, "cpl30": cpl30,
                            "adset": (a.get("adset") or {}).get("name", "∅"),
                            "campaign": camp.get("name", "∅")})
        log.info("  ⏸ PAUSED %s · age=%dd · 30d spend=RM%.0f · CPL30=%s · adset=%r",
                 name, age, spend30, _s(cpl30), (a.get("adset") or {}).get("name", "∅")[:40])

    if paused_rows:
        print(f"Paused {len(paused_rows)} ad(s) today:")
        for r in paused_rows:
            print(f"  ⏸ {r['name']}  (age {r['age']}d · 30d spend RM{r['sp30']:.0f} · "
                  f"CPL30 {_s(r['cpl30'])} · adset {r['adset'][:40]})")
    else:
        print("Nothing met all four criteria today — no new pauses "
              "(adbot-monitor's 20-min CPL gate already catches most losers first).")

    final_summary(log, f"SG daily ops done — {len(yday_sg_rows)} SG sale(s) yesterday, "
                       f"backstop paused {len(paused_rows)} ad(s).")


if __name__ == "__main__":
    main()
