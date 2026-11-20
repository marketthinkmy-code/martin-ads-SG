"""Read-only: how old are the children of SG paying parents? (operator 20 Nov: 「美国那边告诉我，很多付费的家长孩子都是
10 岁以上，你去对回去名单告诉我，新加坡的付费家长，孩子都是几岁为主，验证看看要不要放多点 budget 在 10–15 岁和青春期」).

Paid Student List (RM1997): age from 「你这次最想帮助的孩子几岁？」, else 「Kids Age」. Register: Q1 / 「你这次最想帮助的
孩子几岁？」, else 「Children's Age」. A row with several ages counts once under its oldest child (flagged).
SG = the sale credits an SG老户 / HK campaign (Paid row UTM or the buyer's Register registration, cpa.sale_utms — the
same rule as the monitor); a second view counts rows whose phone starts with 65 (any UTM). MY rows shown for contrast.
Buckets ≤6 / 7–9 / 10–12 / 13–15 / 16+ / 不明. Then SG registrations (UTM SG campaign) by age in the same window, and
paid ÷ registrations per bucket. No names, emails or phones are printed. No writes.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

BUCKETS = ["≤6", "7–9", "10–12", "13–15", "16+", "不明"]


def _sg(c: str) -> bool:
    c = cpa.norm(c)
    return "[sg]" in c or "martin-sg" in c or "martin sg" in c


def _my(c: str) -> bool:
    return "[my]" in cpa.norm(c)


def ages(text: str):
    nums = [int(x) for x in re.findall(r"\d{1,2}", (text or "").replace("１", "1"))]
    return [n for n in nums if 1 <= n <= 19]


def bucket(text: str):
    a = ages(text)
    if not a:
        return "不明", False
    t = (text or "")
    # a range like "10–12 岁" / "7-9" is one band: use its upper end; several children → oldest
    n = max(a)
    multi = len(a) > 1 and not re.search(r"\d\s*[-–~至到]\s*\d", t)
    if n <= 6:
        return "≤6", multi
    if n <= 9:
        return "7–9", multi
    if n <= 12:
        return "10–12", multi
    if n <= 15:
        return "13–15", multi
    return "16+", multi


def col(header, *names):
    low = [(h or "").strip() for h in header]
    for nm in names:
        for i, h in enumerate(low):
            if h == nm:
                return i
    for nm in names:
        for i, h in enumerate(low):
            if nm in h:
                return i
    return -1


def cell(r, i):
    return (r[i] if 0 <= i < len(r) else "").strip()


def main():
    log = get_logger()
    s = load_settings()
    sh = SheetsClient(s.secrets.google_sa_json)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    pv = sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    rv = sh.read_tab(s.cpa.spreadsheet_id, s.cpa.register_tab)
    sales, _c, ph = cpa.parse_sales(pv, s.cpa.price_myr)
    regs, _c2, rh = cpa.parse_sales(rv, 0.0)
    phi = next(i for i, r in enumerate(pv[:8]) if r == ph)
    rhi = next(i for i, r in enumerate(rv[:8]) if r == rh)
    p_rows = [r for r in pv[phi + 1:] if any((x or "").strip() for x in r)]
    r_rows = [r for r in rv[rhi + 1:] if any((x or "").strip() for x in r)]
    p_q, p_k = col(ph, "你这次最想帮助的孩子几岁？"), col(ph, "Kids Age")
    p_tel = col(ph, "whatsapp 號碼", "whatsapp", "phone")
    r_q1, r_q, r_k = col(rh, "Q1. 您这次最希望帮助的孩子，目前几岁？"), col(rh, "你这次最想帮助的孩子几岁？"), col(rh, "Children's Age")
    log.info("Paid 表 %d 行（年龄栏：问卷 %s / Kids Age %s）· 报名表 %d 行", len(p_rows), p_q, p_k, len(r_rows))

    # parse_sales skips rows without any UTM; rebuild row-aligned Sale objects so ages line up with attribution
    em, phc = cpa.person_columns(ph)
    cols = cpa.find_columns(ph)

    def sale_of(r):
        g = lambda k: cell(r, cols.get(k, -1))
        return cpa.Sale(cpa.parse_date(g("date")), cpa.norm(g("campaign")), cpa.norm(g("adset")), cpa.norm(g("ad")),
                        0.0, cpa.person_ids(r, em, phc))

    windows = {"全期": None, "最近 180 天": today - dt.timedelta(days=180), "最近 90 天": today - dt.timedelta(days=90)}
    paid = {w: {"SG（UTM）": Counter(), "SG（电话 65）": Counter(), "MY（UTM）": Counter()} for w in windows}
    raw = Counter()
    multi_n = 0
    for r in p_rows:
        x = sale_of(r)
        if not x.date:
            continue
        utms = cpa.sale_utms(x, regs)
        is_sg = any(_sg(u[0]) for u in utms)
        is_my = any(_my(u[0]) for u in utms) and not is_sg
        tel = re.sub(r"\D", "", cell(r, p_tel))
        is_sg_tel = tel.startswith("65") or (len(tel) == 8 and tel[0] in "89")
        txt = cell(r, p_q) or cell(r, p_k)
        b, multi = bucket(txt)
        if is_sg:
            raw[txt[:20] or "（空）"] += 1
            multi_n += multi
        for w, since in windows.items():
            if since and x.date < since:
                continue
            if is_sg:
                paid[w]["SG（UTM）"][b] += 1
            if is_sg_tel:
                paid[w]["SG（电话 65）"][b] += 1
            if is_my:
                paid[w]["MY（UTM）"][b] += 1

    def line(cn: Counter):
        tot = sum(cn.values())
        known = tot - cn["不明"]
        return " · ".join(f"{b} {cn[b]}" + (f"（{cn[b] / known * 100:.0f}%）" if known and b != "不明" else "")
                          for b in BUCKETS) + f" · 合计 {tot}（有年龄 {known}）"

    log.info("═" * 100)
    log.info("A. 付费家长的孩子年龄（百分比 = 占有年龄的人数）")
    for w in windows:
        for grp, cn in paid[w].items():
            log.info("   %s · %s：%s", w, grp, line(cn))
    log.info("   SG（UTM）里写了几个孩子、算最大那个的：%d 行", multi_n)
    log.info("   SG（UTM）年龄原文最多的 15 种：%s", " | ".join(f"{k} ×{v}" for k, v in raw.most_common(15)))

    # registrations (SG UTM rows) by age, same windows
    reg = {w: Counter() for w in windows}
    cols_r = cpa.find_columns(rh)
    for r in r_rows:
        d = cpa.parse_date(cell(r, cols_r.get("date", -1)))
        camp = cell(r, cols_r.get("campaign", -1))
        if not d or not _sg(camp):
            continue
        b, _m = bucket(cell(r, r_q1) or cell(r, r_q) or cell(r, r_k))
        for w, since in windows.items():
            if since and d < since:
                continue
            reg[w][b] += 1
    log.info("═" * 100)
    log.info("B. SG 报名（UTM 对上 SG campaign）的孩子年龄 · 付费 ÷ 报名")
    for w in windows:
        log.info("   %s · 报名：%s", w, line(reg[w]))
        log.info("   %s · 付费 ÷ 报名：%s", w, " · ".join(
            f"{b} {paid[w]['SG（UTM）'][b]}/{reg[w][b]}" + (f"={paid[w]['SG（UTM）'][b] / reg[w][b] * 100:.1f}%" if reg[w][b] else "")
            for b in BUCKETS))
    final_summary(log, "孩子年龄读完（只读，不印个人资料）")


if __name__ == "__main__":
    main()
