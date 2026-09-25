"""CPA recheck 0925 (read-only) — the Paid Student List finally updated.

① Sheet freshness: latest provably-SG sale date, all SG sales dated ≥ 9/17 (webinar on)
  attributed by ad name with each name's spend context.
② 30d-CPA requalification (window = today-30d) for the watchlist: the current/recent
  board (V12 · V1 流鼻涕 · Carousel · Hook 9 · 测试 5 支 · Hook 7 旧链) plus the
  reopen shortlist that was waiting on the list (准备早餐面包 · V7 · HE04 · 什麼樣的孩子 ·
  dec hook 13) plus every name with a fresh buyer — 30d spend, sales, CPA, headroom to
  RM960, verdict by the operator's discipline. PROPOSAL fodder; changes nothing.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

WEBINAR = dt.date(2026, 9, 17)
WATCH = [
    "Video 12：15歲以上試了五六種方法沒長高", "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好",
    "Carousel：别再逼孩子喝牛奶了", "Hook 9：你有没有发现孩子没有以前那么活泼了？变得越来越安静？自卑？",
    "Hook 1：今晚回家检查三件事", "Hook 3：倒掉牛奶", "Hook 4：保健品叫你丢掉",
    "Hook 6：没有人会告诉你", "Hook 7：算给你看",
    "MAR Video Hook 3: 准备早餐面包", "Video 7：15 岁还没抽高，是不是已经太迟？",
    "Hook Edit 04：不买牛奶给孩子喝", "Video: 什麼樣的孩子基本上不會再長高",
    "dec hook 13：花了几千块买增高 supplement 给孩子吃？",
]


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = today - dt.timedelta(days=30)
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    s30: Dict[str, int] = defaultdict(int)
    fresh: Dict[str, int] = defaultdict(int)
    life_n: Dict[str, int] = defaultdict(int)
    disp: Dict[str, str] = {}
    latest: dt.date | None = None
    n_sg = n_fresh = 0
    for x in sales:
        if not _sg(x.campaign):
            continue
        n_sg += 1
        k = cpa.ad_key(x.ad)
        disp.setdefault(k, (x.ad or "").strip())
        life_n[k] += 1
        if x.date:
            if latest is None or x.date > latest:
                latest = x.date
            if x.date >= d30:
                s30[k] += 1
            if x.date >= WEBINAR:
                n_fresh += 1
                fresh[k] += 1
    log.info("① 名单状态: %d 笔 SG 单 · 最新成交 %s · ≥%s（本场）: %d 笔",
             n_sg, latest, WEBINAR, n_fresh)

    sp30: Dict[str, float] = defaultdict(float)
    for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                time_range={"since": d30.isoformat(),
                                            "until": today.isoformat()}):
        try:
            sp30[cpa.ad_key(r.get("ad_name") or "")] += float(r.get("spend") or 0)
        except (TypeError, ValueError):
            continue

    log.info("═" * 108)
    log.info("② 本场 Fresh Buyer 归因（≥ %s）", WEBINAR)
    if not fresh:
        log.info("  （0 笔 —— 名单还是没进本场的单，或者本场 SG 真的挂零）")
    for k, n in sorted(fresh.items(), key=lambda kv: -kv[1]):
        log.info("  ▸ %-42s 本场 %d 单 · 30d 花 RM%-8.0f 30d 共 %d 单",
                 disp.get(k, k)[:42], n, sp30.get(k, 0.0), s30.get(k, 0))

    log.info("═" * 108)
    log.info("③ 30d-CPA 资格复验（窗口 %s → %s · 达标线 RM%.0f）", d30, today, acc)
    keys = {cpa.ad_key(n): n for n in WATCH}
    for k in fresh:
        keys.setdefault(k, disp.get(k, k))
    for k, label in keys.items():
        sp, n = sp30.get(k, 0.0), s30.get(k, 0)
        cpa30 = sp / n if n else 0.0
        head = n * acc - sp
        if n and cpa30 <= acc:
            v = f"✅ 达标（余量 RM{max(0, head):,.0f}）"
        elif n and cpa30 <= hard:
            v = "🤔 边缘 960-1200"
        elif n:
            v = "❌ 超硬线"
        else:
            v = "— 30d 无单"
        log.info("  %-44s 30d 花 RM%-8.0f %d单 CPA %-9s %s",
                 (disp.get(k) or label)[:44], sp, n,
                 f"RM{cpa30:,.0f}" if n else "—", v)

    final_summary(log, f"CPA recheck: sheet latest {latest}, {n_fresh} webinar-onward SG "
                       f"sales attributed. Read-only — reopen/scale proposal follows in chat.")


if __name__ == "__main__":
    main()
