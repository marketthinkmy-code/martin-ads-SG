"""MARTIN SG — Lead Quality Audit, Phase 1 (read-only, 6 Nov).

Operator brief: audit the SG registrations in the Register tab (G date, H source, J/K/L UTM campaign /
ad set / ad, P–T survey Q1–Q5, U Martin Lead Quality Score computed by GHL). SG only, verified against
the SG ad accounts (SG老户 act_1024930575770087 + HK act_1179668409969241, whose campaigns are [SG]):
  SG✔ 三层   UTM campaign + ad set + ad equal an ad on SG old / HK (campaign may be cut short in the
             sheet: a >=12-char prefix of the Meta name counts)
  SG✔ campaign  UTM campaign equals a campaign on SG old / HK, ad set or ad does not
  SG 标记未验证  J carries [SG] / martin-sg but no SG old / HK campaign has that name
  MY        J carries [MY] / martin-my, or equals a campaign on the MY account (names read only)
  冲突      the campaign name exists on both SG and MY accounts
  无 UTM    J empty (split by H source)
  其他      J set, no market tag, no match
Ad name alone is never used to attribute. Grades from U: A 85–100, B 70–84, C 50–69, D 0–49.
High = U >= 70. Core ICP = U >= 70 and Q2 >= 20 and Q5 >= 16, Q2 / Q5 scored from the raw answer
text with the brief's table (every distinct answer is printed with the score given, so the mapping
can be checked). Rows whose name or email contains "test" / 测试 are set aside as suspected internal
tests (count only). No names, emails or phones are printed — only counts. No writes anywhere.

Date rules (operator 2026-11-06, final): every number is keyed on the registration date (column G),
read at the latest score status; a survey finished days later counts on the original registration
date. Survey Completion Rate = completed in that registration batch / valid registrations of that
batch; Qualified Lead Rate = score >= 70 in the batch / valid registrations of the batch; CPQL = Meta
spend of the same market (SG old + HK), same attribution scope (same campaign / ad set / ad names) and
same registration-date range / qualified leads. Not yet scored = Pending, never low quality. MY is
never mixed in. ADBOT_FROM / ADBOT_TO pick the registration-date range (default: first survey date to
today).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.graph import TransientGraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

SG_ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY = "act_1011719073600566"
TAB = "Register"
COL = {"date": "G", "source": "H", "campaign": "J", "adset": "K", "ad": "L",
       "q1": "P", "q2": "Q", "q3": "R", "q4": "S", "q5": "T", "score": "U"}
# brief's tables; keys are matched as substrings of the NFKC-folded answer (simplified + traditional)
Q2_MAP = [(("身高记录", "身高記錄", "成长变慢", "成長變慢", "长得慢", "長得慢", "有记录孩子身高", "有記錄孩子身高",
           "速度明显变慢", "速度明顯變慢"), 25),
          (("成长评估", "成長評估", "评估", "評估"), 25),
          (("比同龄", "比同齡", "同龄人矮", "同齡人矮", "比较矮", "比較矮"), 20),
          (("不确定", "不確定", "是否正常"), 12),
          (("提前学习", "提前學習", "提前了解"), 5)]
Q5_MAP = [(("专业指导", "專業指導", "持续跟进", "持續跟進"), 20),
          (("系统性", "系統性", "按步骤", "按步驟"), 16),
          (("先了解", "再决定", "再決定"), 10),
          (("免费资讯", "免費資訊", "免费", "免費"), 4)]


def idx(letter):
    return ord(letter) - ord("A")


def letter(i):
    return chr(ord("A") + i) if i < 26 else "A" + chr(ord("A") + i - 26)


def num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def score_answer(ans, table):
    a = (ans or "").strip()
    if not a:
        return None
    n = num(a)
    if n is not None:                                   # the cell already holds a score
        return n
    f = cpa.norm(a)
    for keys, pts in table:
        if any(k in f for k in keys):
            return pts
    return "未对上"


def grade(u):
    if u is None:
        return "缺分"
    return "A" if u >= 85 else "B" if u >= 70 else "C" if u >= 50 else "D"


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
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, TAB)
    hi = next((i for i, r in enumerate(values[:10]) if any("utm" in (c or "").lower() for c in r)), 0)
    header = values[hi]
    rows = values[hi + 1:]
    log.info("Register 分页：表头在第 %d 行 · 数据 %d 行 · 读数 %s SGT", hi + 1, len(rows),
             (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"))
    log.info("全部表头（只列栏名）：%s", " | ".join(f"{letter(i)}={h!r}" for i, h in enumerate(header)))
    for k, L in COL.items():
        i = idx(L)
        log.info("  指定栏 %s（%s）→ 表头 %r", L, k, header[i] if i < len(header) else "（没有这一栏）")
    pii = [i for i, h in enumerate(header) if re.search(r"name|email|e-mail|phone|mobile|whatsapp|姓名|名字|电话|電話|手机|手機",
                                                         (h or "").lower())
           and i not in {idx(COL[k]) for k in ("campaign", "adset", "ad")}]
    log.info("  个人资料栏（只用来认测试 / 重复，不打印内容）：%s", [f"{letter(i)}={header[i]!r}" for i in pii])
    extra = [f"{letter(i)}={h!r}" for i, h in enumerate(header)
             if re.search(r"survey|问卷|問卷|submit|提交|complete|time|时间|時間|date|日期", (h or "").lower())]
    log.info("  可能跟时间 / 问卷有关的栏：%s", extra)

    def cell(r, k):
        i = idx(COL[k])
        return (r[i] if i < len(r) else "").strip()

    # ── Meta: campaign / ad set / ad names on the SG accounts, campaign names on MY ─────────────
    sg_ads, sg_camps, my_camps = set(), set(), set()
    for _label, acct in SG_ACCTS:
        for a in g._get_all(f"{acct}/ads", {"fields": "name,campaign{name},adset{name}", "limit": 500}):
            c = cpa.ad_key((a.get("campaign") or {}).get("name") or "")
            sg_ads.add((c, cpa.ad_key((a.get("adset") or {}).get("name") or ""), cpa.ad_key(a.get("name") or "")))
            sg_camps.add(c)
    my_err = ""
    try:
        for c in g._get_all(f"{MY}/campaigns", {"fields": "name", "limit": 500}):
            my_camps.add(cpa.ad_key(c.get("name") or ""))
    except TransientGraphError:
        raise
    except Exception as exc:
        my_err = str(exc)[:150]
    log.info("Meta：SG老户 + HK 广告 %d 组名字 · campaign %d 个 · MY campaign %d 个%s", len(sg_ads), len(sg_camps),
             len(my_camps), f" · MY 读不到：{my_err}" if my_err else "")

    def camp_in(ck, pool):
        return ck in pool or (len(ck) >= 12 and any(p.startswith(ck) for p in pool))

    def classify(r):
        J, K, L = cell(r, "campaign"), cell(r, "adset"), cell(r, "ad")
        if not J:
            return "无 UTM"
        ck, kk, lk = cpa.ad_key(J), cpa.ad_key(K), cpa.ad_key(L)
        in_sg, in_my = camp_in(ck, sg_camps), camp_in(ck, my_camps)
        if in_sg and in_my:
            return "冲突"
        if in_sg:
            if any(kk == a[1] and lk == a[2] and (ck == a[0] or (len(ck) >= 12 and a[0].startswith(ck))) for a in sg_ads):
                return "SG✔ 三层"
            return "SG✔ campaign"
        t = tag(J)
        if t == "MY" or in_my:
            return "MY"
        if t == "SG":
            return "SG 标记未验证"
        return "其他"

    # ── per row ─────────────────────────────────────────────────────────────────────────────────
    recs, tests, bad_date = [], Counter(), 0
    seen = Counter()
    q_answers = {q: Counter() for q in ("q1", "q2", "q3", "q4", "q5")}
    for r in rows:
        if not any((c or "").strip() for c in r):
            continue
        p = " ".join((r[i] if i < len(r) else "") for i in pii).lower()
        cls = classify(r)
        if re.search(r"\btest|testing|测试|測試", p):
            tests[cls] += 1
            continue
        d = cpa.parse_date(cell(r, "date"))
        if not d:
            bad_date += 1
        ident = hashlib.sha1(p.encode()).hexdigest() if p.strip() else None
        if ident:
            seen[ident] += 1
        qs = [cell(r, q) for q in ("q1", "q2", "q3", "q4", "q5")]
        for q, v in zip(("q1", "q2", "q3", "q4", "q5"), qs):
            if v:
                q_answers[q][v[:60]] += 1
        u = num(cell(r, "score"))
        q2, q5 = score_answer(qs[1], Q2_MAP), score_answer(qs[4], Q5_MAP)
        recs.append({"d": d, "src": cell(r, "source") or "（空）", "cls": cls, "J": cell(r, "campaign"), "K": cell(r, "adset"),
                     "L": cell(r, "ad"), "nq": sum(1 for v in qs if v), "u": u, "q2": q2, "q5": q5,
                     "id": ident, "u_raw": cell(r, "score")})
    for L in ("M", "N", "O"):                           # the older 3-question survey, outside the brief's P–T
        i = idx(L)
        ds = [cpa.parse_date(r[idx("G")]) for r in rows if i < len(r) and (r[i] or "").strip() and idx("G") < len(r)]
        ds = [d for d in ds if d]
        log.info("旧问卷栏 %s %r：有答案 %d 行 · 报名日期 %s ~ %s", L, header[i] if i < len(header) else "", len(ds),
                 min(ds, default=None), max(ds, default=None))
    dup_people = sum(1 for v in seen.values() if v > 1)
    dup_rows = sum(v - 1 for v in seen.values() if v > 1)

    log.info("═" * 100)
    log.info("疑似内部测试（姓名 / 电邮带 test / 测试），已排除：%d 行 · 按归属 %s", sum(tests.values()), dict(tests))
    log.info("日期读不到的行：%d · 同一人重复报名（按姓名+电邮+电话）：%d 人 多出 %d 行", bad_date, dup_people, dup_rows)
    cls_all = Counter(x["cls"] for x in recs)
    log.info("全部行按归属：%s", dict(cls_all))
    for c in cls_all:
        log.info("   %s · H 来源：%s", c, dict(Counter(x["src"] for x in recs if x["cls"] == c).most_common(8)))
    surveyed = [x for x in recs if x["nq"] > 0 or x["u"] is not None]
    start = min((x["d"] for x in surveyed if x["d"]), default=None)
    log.info("最早有问卷 / 分数的报名日期：%s", start)

    # ── survey answers and the Q2 / Q5 mapping ───────────────────────────────────────────────────
    log.info("═" * 100)
    for q in ("q1", "q2", "q3", "q4", "q5"):
        c = q_answers[q]
        log.info("%s（%s 栏）不同答案 %d 种，前 12：", q.upper(), COL[q], len(c))
        for a, n in c.most_common(12):
            sc = score_answer(a, Q2_MAP) if q == "q2" else score_answer(a, Q5_MAP) if q == "q5" else ""
            log.info("    %4d × %r%s", n, a, f" → {sc}" if sc != "" else "")
    u_vals = [x for x in recs if x["u_raw"]]
    log.info("U 栏：有值 %d 行 · 不是数字 %d 行（例：%s）· 超出 0–100 %d 行", len(u_vals),
             sum(1 for x in u_vals if x["u"] is None), [x["u_raw"][:15] for x in u_vals if x["u"] is None][:5],
             sum(1 for x in u_vals if x["u"] is not None and not 0 <= x["u"] <= 100))

    # ── SG scope, operator 2026-11-06 rules ─────────────────────────────────────────────────────
    # Every number is keyed on the registration date (G); a survey done days later still counts on the
    # day the parent registered, read at its latest status. Valid registration = SG-verified, not a
    # suspected test, one per person per registration date. No score yet = Pending, never "low quality".
    sg_cls = ("SG✔ 三层", "SG✔ campaign")
    env_from, env_to = os.environ.get("ADBOT_FROM"), os.environ.get("ADBOT_TO")
    d_from = dt.date.fromisoformat(env_from) if env_from else (start or today)
    d_to = dt.date.fromisoformat(env_to) if env_to else today
    win = [x for x in recs if x["d"] and d_from <= x["d"] <= d_to]
    best = {}
    dups = 0
    for x in win:
        if x["cls"] not in sg_cls:
            continue
        k = (x["d"], x["id"] or id(x))
        if k in best:
            dups += 1
            if (x["u"] is not None, x["nq"]) <= (best[k]["u"] is not None, best[k]["nq"]):
                continue
        best[k] = x
    sg = list(best.values())

    def status(x):
        if x["u"] is not None:
            return "已评分"
        return "缺分待查" if x["nq"] == 5 else "Pending"

    def is_core(x):
        return (x["u"] is not None and x["u"] >= 70 and isinstance(x["q2"], (int, float)) and x["q2"] >= 20
                and isinstance(x["q5"], (int, float)) and x["q5"] >= 16)

    def pct(a, b):
        return f"{a / b * 100:.1f}%" if b else "—"

    def rm(v):
        return f"RM{v:.2f}"

    def stats(xs, spend=None):
        n = len(xs)
        done = sum(1 for x in xs if x["u"] is not None or x["nq"] == 5)
        q = sum(1 for x in xs if x["u"] is not None and x["u"] >= 70)
        core = sum(1 for x in xs if is_core(x))
        st = Counter(status(x) for x in xs)
        sc = [x["u"] for x in xs if x["u"] is not None]
        gr = Counter(grade(u) for u in sc)
        txt = (f"有效报名 {n} · 完成问卷 {done}（Survey Completion {pct(done, n)}）· 已评分 {st['已评分']} · Pending {st['Pending']}"
               f" · 缺分待查 {st['缺分待查']} · 平均分 {f'{sum(sc) / len(sc):.1f}' if sc else '—'} · A{gr['A']} B{gr['B']} C{gr['C']} D{gr['D']}"
               f" · Qualified(≥70) {q}（Qualified Lead Rate {pct(q, n)}）· Core ICP {core}（{pct(core, n)}）")
        if spend is not None:
            txt += (f" · 花费 {rm(spend)} · CPL {rm(spend / n) if n else '—'} · CPQL {rm(spend / q) if q else '—（0 qualified）'}"
                    f" · 每个 Core ICP {rm(spend / core) if core else '—'}")
        return txt

    # Meta spend, SG old + HK only, same date range, per ad (three names) and per day
    sp_ad, sp_day = defaultdict(float), defaultdict(float)
    for _label, acct in SG_ACCTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_increment": 1,
                                                 "fields": "ad_name,adset_name,campaign_name,spend",
                                                 "time_range": json.dumps({"since": d_from.isoformat(), "until": d_to.isoformat()})}):
            v = float(r.get("spend") or 0)
            sp_ad[(cpa.ad_key(r.get("campaign_name") or ""), cpa.ad_key(r.get("adset_name") or ""),
                   cpa.ad_key(r.get("ad_name") or ""))] += v
            sp_day[dt.date.fromisoformat(r["date_start"])] += v
    total_sp = sum(sp_ad.values())

    log.info("═" * 100)
    log.info("A. SG 报名 / 问卷（报名日期 %s ~ %s，读最新评分状态 · 同一天同一人只算 1 次，去掉重复 %d 行）", d_from, d_to, dups)
    log.info("SG 已验证合计：%s", stats(sg, total_sp))
    for c in sg_cls:
        log.info("   其中 %s：%s", c, stats([x for x in sg if x["cls"] == c]))
    others = Counter(x["cls"] for x in win if x["cls"] not in sg_cls)
    log.info("不算进 SG 的报名（同一日期区间）：%s", dict(others))
    log.info("按报名日期（每一批报名，读最新状态）：")
    by_day = defaultdict(list)
    for x in sg:
        by_day[x["d"]].append(x)
    d = d_from
    while d <= d_to:
        log.info("   %s %s · %s", d, "一二三四五六日"[d.weekday()], stats(by_day.get(d, []), sp_day.get(d, 0.0)))
        d += dt.timedelta(days=1)

    log.info("═" * 100)
    log.info("B. 分数分布（SG 已验证，%s ~ %s）：%s", d_from, d_to,
             dict(Counter(grade(x["u"]) if x["u"] is not None else status(x) for x in sg)))

    # ── C / D: by campaign, ad set, ad (spend from the same names, same dates) ───────────────────
    for lvl, n_keys in (("campaign", 1), ("ad set", 2), ("ad", 3)):
        log.info("═" * 100)
        log.info("C/D. 按 %s（%s；花费 = 同名字、同日期区间的 Meta 花费）", lvl,
                 "三层 + 只对上 campaign 的报名" if lvl == "campaign" else "只算三层都对上的报名")
        grp, names, spk = defaultdict(list), {}, defaultdict(float)
        for x in sg:
            if lvl != "campaign" and x["cls"] != "SG✔ 三层":
                continue
            k = (cpa.ad_key(x["J"]), cpa.ad_key(x["K"]), cpa.ad_key(x["L"]))[:n_keys]
            grp[k].append(x)
            names.setdefault(k, " / ".join(v[:50] for v in (x["J"], x["K"], x["L"])[:n_keys]))
        for k3, v in sp_ad.items():
            k = k3[:n_keys]
            hit = next((gk for gk in grp if gk == k or (len(gk[0]) >= 12 and k[0].startswith(gk[0]) and gk[1:] == k[1:])), k)
            spk[hit] += v
            names.setdefault(hit, " / ".join(k))
        keys = sorted(set(grp) | {k for k, v in spk.items() if v > 0},
                      key=lambda k: (-sum(1 for x in grp.get(k, []) if x["u"] is not None and x["u"] >= 70), -spk.get(k, 0.0)))
        for k in keys[:30]:
            log.info("   %s · %s", names[k], stats(grp.get(k, []), spk.get(k, 0.0)))

    # ── E: attribution ──────────────────────────────────────────────────────────────────────────
    log.info("═" * 100)
    tagged = [x for x in win if tag(x["J"]) == "SG" or x["cls"] in sg_cls]
    log.info("E. 归因（报名日期 %s ~ %s）：带 [SG] 或对上 SG 户口的报名 %d · 三层对上 %d · 只对上 campaign %d · 带 [SG] 但户口里没有 %d · 冲突 %d",
             d_from, d_to, len(tagged), sum(1 for x in tagged if x["cls"] == "SG✔ 三层"),
             sum(1 for x in tagged if x["cls"] == "SG✔ campaign"), sum(1 for x in tagged if x["cls"] == "SG 标记未验证"),
             sum(1 for x in tagged if x["cls"] == "冲突"))
    for c in ("SG✔ campaign", "SG 标记未验证", "冲突", "其他"):
        top = Counter((x["J"][:60], x["K"][:30], x["L"][:35]) for x in win if x["cls"] == c).most_common(8)
        if top:
            log.info("   %s 最常见的 UTM（campaign / ad set / ad）：", c)
            for k, n in top:
                log.info("      %3d × %s", n, " / ".join(repr(v) for v in k))
    final_summary(log, f"{d_from}~{d_to} · SG 已验证 {stats(sg, total_sp)}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
