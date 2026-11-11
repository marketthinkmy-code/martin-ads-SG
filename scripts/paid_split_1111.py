"""Paid Student List split SG vs MY, and SG's top ad sets by real sales (read-only, 11 Nov).

Operator 11/11: 「去看回所有 paid student list 记录，分开 新加坡 & 马来西亚 成交的统计。分别 list down top 3 有成交
记录的 ad set for 新加坡，再来建议我」. Every row of the paid sheet ("Paid Student List (RM1997)", shared with
MY) is put in one market by its UTM campaign:
  SG   campaign name exists on SG old / HK (a >=12-char sheet prefix of the Meta name counts), or carries [SG] / martin-sg
  MY   campaign carries [MY] / martin-my, or exists on the MY account (names only, read-only)
  冲突 the name exists on both;  无 UTM  no campaign;  其他  campaign set, no market found
Per market: rows, by month, last 30 / 60 / 90 days. SG ad sets are folded by audience name (same recipe across
campaigns / accounts) → sales all-time / 90 / 60 / 30, last sale, the creatives that sold, SG old + HK spend and
registrations by window (CPA, CPL), and the newest ad set carrying that name (id, status, targeting).
MY: top 5 ad-set names by sales, counts only. No names / phones / emails are read or printed. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.graph import TransientGraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

SG_ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY = "act_1011719073600566"
WINDOWS = (30, 60, 90, 180)


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def aud_key(name):
    n = cpa.norm(name or "")
    n = re.sub(r"interest\s*:\s*", "", n)
    n = re.sub(r"rm\s*\d+", "", n)
    n = n.replace("&", " and ")
    n = re.sub(r"[\s|·:：\-–—_/+()（）\[\]]+", " ", n).strip()
    return n


def tag(c):
    c = cpa.norm(c)
    if "[sg]" in c or "martin-sg" in c or "martin sg" in c:
        return "SG"
    if "[my]" in c or "martin-my" in c or "martin my" in c:
        return "MY"
    return ""


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    hi, cols = 0, cpa.find_columns(values[0] if values else [])
    for i, row in enumerate(values[:8]):
        c = cpa.find_columns(row)
        if c.get("campaign", -1) >= 0 and c.get("ad", -1) >= 0:
            hi, cols = i, c
            break
    header = values[hi]
    log.info("成交表 %r：表头第 %d 行 · 栏位 %s", s.cpa.sales_tab, hi + 1,
             {k: (header[v] if 0 <= v < len(header) else None) for k, v in cols.items()})

    def cell(r, k):
        i = cols.get(k, -1)
        return (r[i] if 0 <= i < len(r) else "").strip()

    # Meta names: SG old + HK campaigns, MY campaigns (names only)
    sg_camps, my_camps = set(), set()
    for _l, acct in SG_ACCTS:
        for c in g._get_all(f"{acct}/campaigns", {"fields": "name", "limit": 500}):
            sg_camps.add(cpa.ad_key(c.get("name") or ""))
    my_err = ""
    try:
        for c in g._get_all(f"{MY}/campaigns", {"fields": "name", "limit": 500}):
            my_camps.add(cpa.ad_key(c.get("name") or ""))
    except TransientGraphError:
        raise
    except Exception as exc:
        my_err = str(exc)[:120]
    log.info("Meta campaign 名：SG老户 + HK %d 个 · MY %d 个%s", len(sg_camps), len(my_camps), f" · MY 读不到：{my_err}" if my_err else "")

    def inpool(ck, pool):
        return bool(ck) and (ck in pool or (len(ck) >= 12 and any(p.startswith(ck) for p in pool)))

    rows, empty = [], 0
    for r in values[hi + 1:]:
        if not any((c or "").strip() for c in r):
            empty += 1
            continue
        J, K, L = cell(r, "campaign"), cell(r, "adset"), cell(r, "ad")
        d = cpa.parse_date(cell(r, "date"))
        ck = cpa.ad_key(J)
        if not J:
            m = "无 UTM"
        else:
            in_sg, in_my, t = inpool(ck, sg_camps), inpool(ck, my_camps), tag(J)
            if in_sg and in_my:
                m = "冲突"
            elif in_sg or (t == "SG" and not in_my):
                m = "SG"
            elif in_my or t == "MY":
                m = "MY"
            else:
                m = "其他"
        rows.append({"d": d, "m": m, "J": J, "K": K, "L": L})
    log.info("成交表数据 %d 行（空行 %d）· 日期读不到 %d 行", len(rows), empty, sum(1 for x in rows if not x["d"]))

    # ── A: market split ──
    log.info("═" * 110)
    log.info("A. 成交按市场（全部行）")
    for m in ("SG", "MY", "冲突", "无 UTM", "其他"):
        xs = [x for x in rows if x["m"] == m]
        dated = [x["d"] for x in xs if x["d"]]
        win = " · ".join(f"{w} 天 {sum(1 for d in dated if d > today - dt.timedelta(days=w))}" for w in WINDOWS)
        log.info("  %-6s 全部 %d 笔 · %s · 最早 %s · 最近 %s", m, len(xs), win, min(dated, default=None), max(dated, default=None))
    log.info("  按月（SG / MY / 无 UTM / 其他）：")
    months = sorted({x["d"].strftime("%Y-%m") for x in rows if x["d"]})
    for mo in months[-12:]:
        c = Counter(x["m"] for x in rows if x["d"] and x["d"].strftime("%Y-%m") == mo)
        log.info("    %s · SG %d · MY %d · 无 UTM %d · 其他 %d · 冲突 %d", mo, c["SG"], c["MY"], c["无 UTM"], c["其他"], c["冲突"])
    oth = Counter(x["J"][:60] for x in rows if x["m"] == "其他").most_common(6)
    if oth:
        log.info("  「其他」最常见的 UTM campaign：%s", oth)

    # ── B: SG ad sets by sales ──
    sg = [x for x in rows if x["m"] == "SG"]
    by = defaultdict(list)
    no_set = 0
    for x in sg:
        if not x["K"]:
            no_set += 1
            continue
        by[aud_key(x["K"])].append(x)
    log.info("═" * 110)
    log.info("B. SG 成交按 ad set 名（同名受众跨 campaign / 户口合并）· SG 成交 %d 笔，其中没有 UTM ad set %d 笔", len(sg), no_set)

    sp = {w: defaultdict(float) for w in WINDOWS + (3650,)}
    ld = {w: defaultdict(float) for w in WINDOWS + (3650,)}
    for _l, acct in SG_ACCTS:
        for w in WINDOWS + (3650,):
            params = {"level": "adset", "limit": 100, "fields": "adset_name,spend,actions"}
            if w == 3650:
                params["date_preset"] = "maximum"
            else:
                params["time_range"] = json.dumps({"since": (today - dt.timedelta(days=w)).isoformat(), "until": today.isoformat()})
            for r in g._get_all(f"{acct}/insights", params):
                k = aud_key(r.get("adset_name") or "")
                sp[w][k] += _f(r.get("spend"))
                ld[w][k] += extract_results(r.get("actions"), tok)

    newest_id, nt, nlabel = {}, {}, {}
    live = defaultdict(int)
    for label, acct in SG_ACCTS:
        for a in g._get_all(f"{acct}/adsets", {"fields": "id,name,created_time,effective_status", "limit": 200}):
            k = aud_key(a.get("name") or "")
            if a.get("effective_status") == "ACTIVE":
                live[k] += 1
            if (a.get("created_time") or "") > nt.get(k, ""):
                nt[k], newest_id[k], nlabel[k] = a.get("created_time") or "", a["id"], label
    newest = {}

    def describe(k):
        if k not in newest_id:
            return "（SG老户 / HK 没找到同名 ad set）"
        if k not in newest:
            a = g.get_object(newest_id[k], "id,name,created_time,effective_status,daily_budget,targeting,campaign{name}")
            t = a.get("targeting") or {}
            ints = [x.get("name") for fs in t.get("flexible_spec") or [] for kind in ("interests", "behaviors", "family_statuses")
                    for x in fs.get(kind) or []]
            loc = (t.get("geo_locations") or {})
            newest[k] = (f"{nlabel[k]} ad set {a['id']} {a.get('name')!r}（{a.get('effective_status')}，建于 {(a.get('created_time') or '')[:10]}，"
                         f"campaign {(a.get('campaign') or {}).get('name', '')[:60]!r}）· {t.get('age_min')}-{t.get('age_max')} 岁 · "
                         f"Adv+ 受众 {'开' if (t.get('targeting_automation') or {}).get('advantage_audience') else '关'} · "
                         f"地区 {loc.get('countries')} {loc.get('location_types')} · 兴趣 {len(ints)} 个：{'/'.join(ints[:8]) or 'broad'}")
        return newest[k]

    def line(k, xs):
        dated = sorted(x["d"] for x in xs if x["d"])
        n = {w: sum(1 for d in dated if d > today - dt.timedelta(days=w)) for w in WINDOWS}
        parts = []
        for w in (90, 180, 3650):
            nn = len(xs) if w == 3650 else n[w]
            spend, leads = sp[w][k], ld[w][k]
            lab = "全期" if w == 3650 else f"{w} 天"
            parts.append(f"{lab} {nn} 单 · 花 RM{spend:,.2f} · CPA {('RM' + format(spend / nn, ',.2f')) if nn else '—'} · "
                         f"报名 {int(leads)} · CPL {('RM' + format(spend / leads, ',.2f')) if leads else '—'}")
        return n, dated, parts

    ranked = sorted(by.items(), key=lambda kv: (-len(kv[1]), -max((x["d"] or dt.date.min).toordinal() for x in kv[1])))
    for i, (k, xs) in enumerate(ranked[:12], 1):
        n, dated, parts = line(k, xs)
        log.info("▌%d. %s · 全期 SG 成交 %d 笔 · 30 天 %d · 60 天 %d · 90 天 %d · 180 天 %d · 最后一笔 %s · 现在在跑的同名 ad set %d 个",
                 i, k[:60], len(xs), n[30], n[60], n[90], n[180], dated[-1] if dated else None, live[k])
        for p in parts:
            log.info("     %s", p)
        ads = Counter(x["L"][:45] for x in xs).most_common(6)
        log.info("     成交的片（全期）：%s", " · ".join(f"{a} ×{c}" for a, c in ads))
        ads90 = Counter(x["L"][:45] for x in xs if x["d"] and x["d"] > today - dt.timedelta(days=90)).most_common(4)
        if ads90:
            log.info("     90 天内成交的片：%s", " · ".join(f"{a} ×{c}" for a, c in ads90))
        camps = Counter(x["J"][:60] for x in xs).most_common(3)
        log.info("     成交的 campaign：%s", " · ".join(f"{a} ×{c}" for a, c in camps))
        log.info("     最新同名 ad set：%s", describe(k) if i <= 6 else newest_id.get(k, "—"))

    # ── C: MY ad sets (counts only) ──
    my = [x for x in rows if x["m"] == "MY"]
    log.info("═" * 110)
    log.info("C. MY 成交按 ad set 名（只数笔数，不读 MY 花费）· MY 成交 %d 笔", len(my))
    for k, c in Counter(aud_key(x["K"]) for x in my if x["K"]).most_common(5):
        d = sorted(x["d"] for x in my if x["K"] and aud_key(x["K"]) == k and x["d"])
        log.info("   %s · %d 笔 · 90 天 %d · 最后一笔 %s", k[:60], c, sum(1 for y in d if y > today - dt.timedelta(days=90)),
                 d[-1] if d else None)

    final_summary(log, "SG " + str(len(sg)) + " 笔 / MY " + str(len(my)) + " 笔 · SG top 3 ad set: " +
                  " | ".join(f"{k[:35]} {len(xs)} 单" for k, xs in ranked[:3]))


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
