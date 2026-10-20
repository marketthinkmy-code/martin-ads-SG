"""What makes an SG ad cheap AND selling? (read-only, 20 Oct)

Operator: SG 广告剩下 2 个 … 跑到便宜且有成绩的，是有什么规律吗？我想看可以再怎么 scale SG.
Everything summed by script (rule 7). SG market = [SG] campaigns on SG old + HK, last 365 days.
  1. theme of the video (regex on the ad name) → spend, leads, CPL, sales, CPA, 买家转化
  2. account (SG old vs HK) for the same window
  3. creative ranking by SG sales (sales matched on the sheet's UTM ad name)
  4. audience ranking by SG sales (sheet's UTM ad set — rule 5)
  5. the winning creatives × every audience they ran in, and sale-proven audiences not yet tried
  6. ad-set days bucketed by that day's spend → CPL per bucket (does pushing budget hurt?)
  7. MY creatives with cheap leads that never ran in SG (MY read only)
No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

SG_ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY_ACCT = "act_1011719073600566"
DAYS = 365
THEMES = [
    ("食物/牛奶/挑食", re.compile(r"牛奶|milo|美禄|美祿|挑食|面包|麵包|早餐|饮食|飲食|营养|營養|零食|食物|kaya|food|milk|吃|喝", re.I)),
    ("真人见证/故事", re.compile(r"林[書书]豪|story|见证|見證|长高了|長高了|\d+\s*cm", re.I)),
    ("青少年 15岁+/中学", re.compile(r"1[5-8]\s*[岁歲]|中[学學]|青春期|teen", re.I)),
    ("补品/花了钱", re.compile(r"花了|几千|幾千|补品|補品|钙|鈣|保健", re.I)),
    ("线下见面", re.compile(r"[線线]下")),
    ("父母身高/遗传", re.compile(r"爸妈|爸媽|父母|遗传|遺傳|不高", re.I)),
    ("睡眠/运动", re.compile(r"睡|运动|運動|跳", re.I)),
]


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _sg(c):
    c = cpa.norm(c)
    return "[sg]" in c or "martin-sg" in c or "martin sg" in c


def _my(c):
    c = cpa.norm(c)
    return "[my]" in c or "martin-my" in c or "martin my" in c


def aud_key(name):
    n = cpa.norm(name or "")
    n = re.sub(r"interest\s*:\s*", "", n)
    n = re.sub(r"rm\s*\d+", "", n)
    n = n.replace("&", " and ")
    return re.sub(r"[\s|·:：\-–—_/+()（）\[\]]+", " ", n).strip()


def theme(name):
    for label, pat in THEMES:
        if pat.search(name or ""):
            return label
    return "其他"


def fmt(sp, ld, n):
    return (f"花 RM{sp:,.0f} · {int(ld)} lead · CPL {('RM' + format(sp / ld, ',.0f')) if ld else '∞'} · "
            f"成交 {n} · CPA {('RM' + format(sp / n, ',.0f')) if n else '—'} · 买家转化 {(format(n / ld * 100, '.0f') + '%') if ld and n else '—'}")


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = today - dt.timedelta(days=DAYS)
    tr = json.dumps({"since": since.isoformat(), "until": today.isoformat()})

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), s.cpa.price_myr)
    s_ad, s_aud, s_pair, s_my = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    n_sg = 0
    for x in sales:
        if not x.date or x.date < since:
            continue
        if _my(x.campaign):
            s_my[cpa.ad_key(x.ad)] += 1
        if not _sg(x.campaign):
            continue
        n_sg += 1
        s_ad[cpa.ad_key(x.ad)] += 1
        if x.adset:
            s_aud[aud_key(x.adset)] += 1
            s_pair[(cpa.ad_key(x.ad), aud_key(x.adset))] += 1
    log.info("成交表：%s 起 SG 成交 %d 笔（带 UTM ad set 的 %d 笔）", since, n_sg, sum(s_aud.values()))

    # ad-level rows, SG market
    rows = []  # (acct, ad_key, ad_name, aud_key, spend, leads)
    for label, acct in SG_ACCTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_range": tr,
                                                  "fields": "campaign_name,adset_name,ad_name,spend,actions"}):
            if not _sg(r.get("campaign_name") or ""):
                continue
            rows.append((label, cpa.ad_key(r.get("ad_name") or ""), r.get("ad_name") or "", aud_key(r.get("adset_name") or ""),
                         _f(r.get("spend")), extract_results(r.get("actions"), tok)))

    by_ad = defaultdict(lambda: [0.0, 0.0]); names = {}
    by_acct = defaultdict(lambda: [0.0, 0.0])
    by_aud = defaultdict(lambda: [0.0, 0.0])
    by_pair = defaultdict(lambda: [0.0, 0.0])
    by_ad_acct = defaultdict(lambda: [0.0, 0.0])
    for label, k, nm, a, sp, ld in rows:
        for d, key in ((by_ad, k), (by_acct, label), (by_aud, a), (by_pair, (k, a)), (by_ad_acct, (k, label))):
            d[key][0] += sp; d[key][1] += ld
        names.setdefault(k, nm)

    # 1. themes
    th = defaultdict(lambda: [0.0, 0.0, 0, 0])
    for k, (sp, ld) in by_ad.items():
        t = th[theme(names[k])]
        t[0] += sp; t[1] += ld; t[2] += s_ad.get(k, 0); t[3] += 1
    log.info("═" * 120)
    log.info("1. 按视频主题（%d 天，SG 老户 + HK 的 [SG] campaign）", DAYS)
    for lab, (sp, ld, n, c) in sorted(th.items(), key=lambda kv: -kv[1][2]):
        log.info("  %-18s %3d 支片 · %s", lab, c, fmt(sp, ld, n))

    # 2. accounts (sales split by which account the ad lived in is not on the sheet; spend/lead only)
    log.info("═" * 120)
    log.info("2. 按账户（同窗口）")
    for lab, (sp, ld) in by_acct.items():
        log.info("  %-5s 花 RM%.0f · %d lead · CPL %s", lab, sp, int(ld), f"RM{sp / ld:,.0f}" if ld else "∞")
    both = [k for k in by_ad if (k, "SG老") in by_ad_acct and (k, "HK") in by_ad_acct
            and by_ad_acct[(k, "SG老")][0] >= 90 and by_ad_acct[(k, "HK")][0] >= 90]
    log.info("  两个账户都花过 ≥RM90 的同一支片 %d 支：", len(both))
    hk_better = 0
    for k in sorted(both, key=lambda k: -by_ad[k][0]):
        o, h = by_ad_acct[(k, "SG老")], by_ad_acct[(k, "HK")]
        co = o[0] / o[1] if o[1] else float("inf"); ch = h[0] / h[1] if h[1] else float("inf")
        hk_better += ch < co
        log.info("    %-40s SG老 RM%.0f/%d lead CPL %s  |  HK RM%.0f/%d lead CPL %s", names[k][:40], o[0], int(o[1]),
                 f"{co:,.0f}" if o[1] else "∞", h[0], int(h[1]), f"{ch:,.0f}" if h[1] else "∞")
    log.info("  其中 HK 的 CPL 比 SG 老户低的：%d / %d 支", hk_better, len(both))

    # 3. creatives by sales
    log.info("═" * 120)
    log.info("3. 视频排名（按 SG 成交，再按 CPL）· 至少 1 单或花过 RM300")
    ranked = sorted(by_ad, key=lambda k: (-s_ad.get(k, 0), (by_ad[k][0] / by_ad[k][1]) if by_ad[k][1] else 1e9))
    for k in ranked:
        sp, ld = by_ad[k]
        if not s_ad.get(k) and sp < 300:
            continue
        log.info("  %-44s [%s] %s", names[k][:44], theme(names[k]), fmt(sp, ld, s_ad.get(k, 0)))

    # 4. audiences by sales
    log.info("═" * 120)
    log.info("4. 受众排名（成交表 UTM ad set · 规矩 5）")
    top_aud = sorted(set(by_aud) | set(s_aud), key=lambda a: (-s_aud.get(a, 0), -by_aud[a][1]))
    for a in top_aud[:15]:
        sp, ld = by_aud[a]
        log.info("  %-44s %s", a[:44], fmt(sp, ld, s_aud.get(a, 0)))
    proven = [a for a in top_aud if s_aud.get(a, 0) >= 3]

    # 5. winners × audiences
    log.info("═" * 120)
    log.info("5. 便宜又出单的片 × 跑过的受众（✔ 跑过 / ✘ 有 ≥3 单记录但这支片没跑过）")
    winners = [k for k in ranked if s_ad.get(k) and by_ad[k][1] and by_ad[k][0] / by_ad[k][1] <= 90][:8]
    for k in winners:
        log.info("  ▌%s · %s", names[k][:50], fmt(by_ad[k][0], by_ad[k][1], s_ad.get(k, 0)))
        for (kk, a), (sp, ld) in sorted(by_pair.items(), key=lambda kv: -kv[1][0]):
            if kk == k and sp >= 20:
                log.info("      ✔ %-40s %s", a[:40], fmt(sp, ld, s_pair.get((k, a), 0)))
        missing = [a for a in proven if (k, a) not in by_pair]
        log.info("      ✘ 没跑过：%s", " · ".join(f"{a[:30]}（{s_aud[a]} 单）" for a in missing[:8]) or "—")

    # 6. spend-per-day buckets
    log.info("═" * 120)
    log.info("6. 每个 ad set 每天的花费分档 → CPL（最近 180 天，SG 市场）")
    bk = [(0, 60), (60, 100), (100, 150), (150, 250), (250, 10 ** 6)]
    agg = defaultdict(lambda: [0.0, 0.0, 0])
    daily = []
    for _, acct in SG_ACCTS:
        for i in range(6):  # 30-day chunks: one 180-day daily pull is refused by Meta
            lo_d, hi_d = today - dt.timedelta(days=180 - 30 * i), today - dt.timedelta(days=150 - 30 * i + (0 if i == 5 else 1))
            try:
                daily += list(g._get_all(f"{acct}/insights", {"level": "adset", "limit": 500, "time_increment": 1,
                                                             "time_range": json.dumps({"since": lo_d.isoformat(), "until": hi_d.isoformat()}),
                                                             "fields": "campaign_name,adset_id,spend,actions"}))
            except Exception as e:  # keep going; say which chunk is missing
                log.info("  （%s %s–%s 拉不到：%s）", acct, lo_d, hi_d, str(e)[:80])
    for r in daily:
        if not _sg(r.get("campaign_name") or ""):
            continue
        sp = _f(r.get("spend"))
        if sp < 5:
            continue
        for lo, hi in bk:
            if lo <= sp < hi:
                a = agg[(lo, hi)]; a[0] += sp; a[1] += extract_results(r.get("actions"), tok); a[2] += 1
    for lo, hi in bk:
        sp, ld, n = agg[(lo, hi)]
        log.info("  当天花 RM%-4d–%-7s %4d 个 ad set 天 · 花 RM%.0f · %d lead · CPL %s", lo, hi if hi < 10 ** 6 else "以上", n, sp, int(ld),
                 f"RM{sp / ld:,.0f}" if ld else "∞")

    # 7. MY creatives never run in SG
    log.info("═" * 120)
    log.info("7. MY 便宜出 lead、但 SG 市场没跑过的片（MY 最近 180 天，只读）")
    tr180 = json.dumps({"since": (today - dt.timedelta(days=180)).isoformat(), "until": today.isoformat()})
    my = defaultdict(lambda: [0.0, 0.0]); myn = {}
    for r in g._get_all(f"{MY_ACCT}/insights", {"level": "ad", "limit": 500, "time_range": tr180,
                                                 "fields": "ad_name,spend,actions"}):
        k = cpa.ad_key(r.get("ad_name") or "")
        my[k][0] += _f(r.get("spend")); my[k][1] += extract_results(r.get("actions"), tok); myn.setdefault(k, r.get("ad_name") or "")
    cand = [k for k, (sp, ld) in my.items() if ld >= 5 and sp / ld <= 50 and k not in by_ad]
    for k in sorted(cand, key=lambda k: (-s_my.get(k, 0), my[k][0] / my[k][1])):
        sp, ld = my[k]
        log.info("  %-46s [%s] MY 花 RM%.0f · %d lead · CPL RM%.0f · MY 成交 %d", myn[k][:46], theme(myn[k]), sp, int(ld), sp / ld, s_my.get(k, 0))
    final_summary(log, "sg patterns · read-only")


if __name__ == "__main__":
    main()
