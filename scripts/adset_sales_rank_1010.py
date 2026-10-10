"""Which AUDIENCE sells? (read-only, 10 Oct) — rank ad-set targetings by real SG sales.

Operator: 推荐用什么 ad set 好？最好是成交最好的，为数据支持. The sheet carries the UTM ad-set
name per paid sale ({{adset.name}}), Meta carries spend + registrations per ad set, and
ad sets with the same name are the same audience recipe across campaigns / accounts
(old SG + HK). Fold both by audience name → sales, CPA, leads, 买家转化, CPL for 30d / 60d /
90d, plus which creatives sold inside each audience and the audience's targeting signature.
No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCOUNTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
WINDOWS = (30, 60, 90)


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def aud_key(name: str) -> str:
    """Audience recipe key: drop 'Interest:' prefixes, budgets, punctuation; casefold."""
    n = cpa.norm(name or "")
    n = re.sub(r"interest\s*:\s*", "", n)
    n = re.sub(r"rm\s*\d+", "", n)
    n = re.sub(r"[\s|·:：\-–—_/+()（）\[\]]+", " ", n).strip()
    return n


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    # ── sheet: SG sales by audience ──
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n_sales: Dict[int, Dict[str, int]] = {w: defaultdict(int) for w in WINDOWS}
    n_all: Dict[str, int] = defaultdict(int)
    creatives: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    raw_names: Dict[str, set] = defaultdict(set)
    no_adset = 0
    for x in sales:
        if not x.date or not _sg(x.campaign):
            continue
        aname = getattr(x, "adset", "") or ""
        if not aname:
            no_adset += 1
            continue
        k = aud_key(aname)
        raw_names[k].add(aname[:40])
        n_all[k] += 1
        if x.date >= today - dt.timedelta(days=90):
            creatives[k][(x.ad or "")[:30]] += 1
        for w in WINDOWS:
            if x.date >= today - dt.timedelta(days=w):
                n_sales[w][k] += 1
    log.info("成交表：SG 单带 UTM ad set 的 %d 笔 · 没有 ad set 的 %d 笔（算不进受众）", sum(n_all.values()), no_adset)

    # ── Meta: spend + leads by audience ──
    sp: Dict[int, Dict[str, float]] = {w: defaultdict(float) for w in WINDOWS}
    ld: Dict[int, Dict[str, float]] = {w: defaultdict(float) for w in WINDOWS}
    for _, acct in ACCOUNTS:
        for w in WINDOWS:
            since = today - dt.timedelta(days=w)
            for r in g._get_all(f"{acct}/insights",
                                {"level": "adset", "limit": 500, "fields": "adset_name,spend,actions",
                                 "time_range": json.dumps({"since": since.isoformat(), "until": today.isoformat()})}):
                k = aud_key(r.get("adset_name") or "")
                raw_names[k].add((r.get("adset_name") or "")[:40])
                sp[w][k] += _f(r.get("spend"))
                ld[w][k] += extract_results(r.get("actions"), token)

    # ── targeting signature per audience (newest ad set carrying that name) ──
    sig: Dict[str, str] = {}
    sig_time: Dict[str, str] = {}
    for label, acct in ACCOUNTS:
        for a in g._get_all(f"{acct}/adsets", {"fields": "id,name,created_time,targeting", "limit": 800}):
            k = aud_key(a.get("name") or "")
            if (a.get("created_time") or "") <= sig_time.get(k, ""):
                continue
            t = a.get("targeting") or {}
            ints = [x.get("name") for fs in t.get("flexible_spec") or [] for kind in
                    ("interests", "behaviors", "family_statuses") for x in fs.get(kind) or []]
            genders = {1: "男", 2: "女"}.get((t.get("genders") or [0])[0], "全部") if t.get("genders") else "全部"
            sig[k] = (f"{label} {a['id']} · {t.get('age_min')}-{t.get('age_max')} · {genders} · "
                      f"Adv+{'开' if (t.get('targeting_automation') or {}).get('advantage_audience') else '关'} · "
                      f"{'/'.join(ints[:5]) if ints else 'broad'}")
            sig_time[k] = a.get("created_time") or ""

    keys = {k for w in WINDOWS for k in list(n_sales[w]) + list(sp[w])}
    rows = []
    for k in keys:
        s60, l60, n60 = sp[60][k], ld[60][k], n_sales[60][k]
        rows.append((n60, -(s60 / n60) if n60 else 0, k))
    log.info("═" * 120)
    log.info("受众排名（按 60d 单数，再按 CPA）· 每行：30d / 60d / 90d 的 单 · 花 · CPA · lead · 买家转化(单÷lead) · CPL")
    for n60, _, k in sorted(rows, reverse=True):
        if not any(n_sales[w][k] for w in WINDOWS) and sp[90][k] < 300:
            continue  # never sold and barely spent: noise
        parts = []
        for w in WINDOWS:
            n, spend, leads = n_sales[w][k], sp[w][k], ld[w][k]
            parts.append(f"{w}d {n}单 RM{spend:,.0f} CPA {spend / n:,.0f} {int(leads)}L 转化 {n / leads * 100:.0f}% CPL {spend / leads:,.0f}"
                         if n and leads else
                         f"{w}d {n}单 RM{spend:,.0f} {'CPA ' + format(spend / n, ',.0f') + ' ' if n else ''}{int(leads)}L"
                         f"{' CPL ' + format(spend / leads, ',.0f') if leads else ''}")
        log.info("▌%s  （全史 SG 单 %d）", k[:40], n_all[k])
        for p in parts:
            log.info("    %s", p)
        if creatives[k]:
            top = sorted(creatives[k].items(), key=lambda kv: -kv[1])[:4]
            log.info("    90d 成交的片：%s", " · ".join(f"{nm} ×{c}" for nm, c in top))
        log.info("    名字：%s", " / ".join(sorted(raw_names[k]))[:150])
        if sig.get(k):
            log.info("    定向：%s", sig[k])
    final_summary(log, "audience rank done · read-only")


if __name__ == "__main__":
    main()
