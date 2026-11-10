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
text: GHL's exact option wording mapped to the brief's table (operator 2026-11-10; an answer not in
the list is UNMAPPED / NEEDS REVIEW, never "not Core ICP"; every distinct answer is printed with its
mapping). Returning Lead = the same person (name + email + phone) has an earlier registration date;
the registration keeps its own UTM attribution, but First-time and Returning are counted apart. The
SG total and per-day CPQL use all SG old + HK spend and are labelled Blended, never compared with one
ad's CPQL. Rows whose name or email contains "test" / 测试 are set aside as suspected internal
tests (count only). No names, emails or phones are printed — only counts. No writes anywhere.

Date rules (operator 2026-11-06, final): every number is keyed on the registration date (column G),
read at the latest score status; a survey finished days later counts on the original registration
date. Survey Completion Rate = completed in that registration batch / valid registrations of that
batch; Qualified Lead Rate = score >= 70 in the batch / valid registrations of the batch; CPQL = Meta
spend of the same market (SG old + HK), same attribution scope (same campaign / ad set / ad names) and
same registration-date range / qualified leads. Not yet scored = Pending, never low quality. MY is
never mixed in. ADBOT_FROM / ADBOT_TO pick the registration-date range (default: first survey date to
today).

Supplement + rule lock (operator 2026-11-06): the survey analysis starts provisionally on 2026-11-06
(ADBOT_SURVEY_LAUNCH overrides); earlier registrations with no answer are "Pre-launch Registration /
Invitation Unknown" (never "not invited" / "refused") and stay out of every rate denominator; after it
they are "Eligible Pending". Per batch: raw rows and de-duplicated people, Valid Registrations
(eligible), Survey Completed, Completion Rate, Score Coverage Rate, Pending, Qualified (>= 70) over
Valid and over Completed (different denominators), Core ICP. Preliminary CPQL = matched spend /
qualified whenever qualified > 0, else N/A (never RM0). Fewer than ADBOT_MIN_SCORED (10) scored =
PRELIMINARY / INSUFFICIENT DATA, else WATCH; batches younger than ADBOT_MATURE_DAYS (3) are flagged not
mature. Computability and decision reliability are reported apart; this report never says SCALE /
REDUCE / PAUSE and does not touch the CPL / CPA monitor. No-UTM surveys are not called a tracking error without
evidence; the UTM-retention check compares surveyed vs not-surveyed rows and same-person rows. The SG
accounts' billing currency is read and must be one currency. A CPQL readiness checklist closes the run.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import unicodedata
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
TAB = "Register"
PRE = "Pre-launch Registration / Invitation Unknown"   # before the provisional survey start, no answer
COL = {"date": "G", "source": "H", "campaign": "J", "adset": "K", "ad": "L",
       "q1": "P", "q2": "Q", "q3": "R", "q4": "S", "q5": "T", "score": "U"}
# GHL option text, exact (operator 2026-11-10): Q2 / Q5 scores from the brief's table matched to GHL's real
# option wording; Q1 / Q3 / Q4 are only recognised (their score table is not on file). An answer not in
# the list is UNMAPPED / NEEDS REVIEW, never "not Core ICP". Only wording seen in Register is listed; not yet seen:
# Q2 "只是提前学习" option and any other Q1 age band.
UNMAPPED = "UNMAPPED / NEEDS REVIEW"
Q2_MAP = {"有记录孩子身高，发现最近长高速度明显变慢": 25,
          "曾经带孩子做成长评估，希望进一步了解或改善": 25,
          "孩子明显比同龄人矮，担心差距越来越大": 20,
          "不确定孩子目前的成长情况是否正常": 12}
Q5_MAP = {"希望有专业人士了解孩子的情况，给予适合的指导，并持续跟进": 20,
          "希望有一套清楚的方法，可以跟着步骤帮助孩子改善生活习惯": 16,   # = 系统性方法、按步骤执行 (operator 11/10)
          "希望先了解孩子成长的关键因素，再决定下一步": 10,
          "主要想获得一些免费的成长知识和建议": 4}
Q1_OPTS = {"3–6 岁", "10–12 岁", "13–15 岁"}           # only options seen in Register so far; others -> UNMAPPED
Q3_OPTS = {"希望未来 1 个月内开始", "希望未来 1–3 个月内开始", "暂时没有计划，想先了解资讯"}
Q4_OPTS = {"愿意长期配合，并定期记录孩子的成长变化", "愿意在多数日子安排时间，协助孩子执行",
           "想先了解方法，再尝试适合的部分", "目前较难安排时间，主要想先听建议"}


def _canon(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[‐-―−~～-]", "–", s)            # every dash / tilde form -> en dash
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*([,.:;!?()，。、！？：；（）])\s*", r"\1", s)   # no spaces around punctuation (NFKC makes it ASCII)
    return s.replace(",", "，")


Q2_C = {_canon(k): v for k, v in Q2_MAP.items()}
Q5_C = {_canon(k): v for k, v in Q5_MAP.items()}
Q_OPTS_C = {"q1": {_canon(k) for k in Q1_OPTS}, "q3": {_canon(k) for k in Q3_OPTS}, "q4": {_canon(k) for k in Q4_OPTS}}


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
    """Exact GHL option text -> score; empty -> None; anything else -> UNMAPPED."""
    a = (ans or "").strip()
    if not a:
        return None
    n = num(a)
    if n is not None:                                   # the cell already holds a score
        return n
    return table.get(_canon(a), UNMAPPED)


def known_answer(ans, q):
    a = (ans or "").strip()
    if not a:
        return None
    return "OK" if _canon(a) in Q_OPTS_C[q] else UNMAPPED


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
    for ri, r in enumerate(rows):
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
        q2, q5 = score_answer(qs[1], Q2_C), score_answer(qs[4], Q5_C)
        qk = {q: known_answer(v, q) for q, v in zip(("q1", "q3", "q4"), (qs[0], qs[2], qs[3]))}
        recs.append({"d": d, "src": cell(r, "source") or "（空）", "cls": cls, "J": cell(r, "campaign"), "K": cell(r, "adset"),
                     "L": cell(r, "ad"), "nq": sum(1 for v in qs if v), "u": u, "q2": q2, "q5": q5,
                     "id": ident, "u_raw": cell(r, "score"), "row": hi + 2 + ri, "qk": qk})
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
            sc = (score_answer(a, Q2_C) if q == "q2" else score_answer(a, Q5_C) if q == "q5"
                  else ("已识别" if known_answer(a, q) == "OK" else UNMAPPED))
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
    env_launch = os.environ.get("ADBOT_SURVEY_LAUNCH")
    launch = dt.date.fromisoformat(env_launch or "2026-11-06")       # operator 2026-11-06: provisional start
    min_scored = int(os.environ.get("ADBOT_MIN_SCORED") or 10)       # decision reliability only, never a CPQL gate
    min_total = int(os.environ.get("ADBOT_MIN_TOTAL") or 30)
    mature_days = int(os.environ.get("ADBOT_MATURE_DAYS") or 3)      # batches younger than this are not mature
    log.info("问卷分析起始日（暂定，不代表 %s 报名的人都收到邀请）：%s · 之前报名、又没有答案的 = %s，"
             "不进比率分母，也不算拒绝填写", launch, launch, PRE)
    g_fmt = Counter(re.sub(r"\d", "9", cell(r, "date"))[:25] for r in rows[-300:] if cell(r, "date"))
    log.info("G 栏日期格式（最近 300 行，数字换成 9）：%s", dict(g_fmt.most_common(3)))
    win = [x for x in recs if x["d"] and d_from <= x["d"] <= d_to]
    best, raw_n = {}, Counter()
    dups = 0
    for x in win:
        if x["cls"] not in sg_cls:
            continue
        k = (x["d"], x["id"] or id(x))
        raw_n[k] += 1
        if k in best:
            dups += 1
            if (x["u"] is not None, x["nq"]) <= (best[k]["u"] is not None, best[k]["nq"]):
                continue
        best[k] = x
    for k, x in best.items():
        x["raw_n"] = raw_n[k]
    sg = list(best.values())

    first_reg = {}
    for x in recs:
        if x["id"] and x["d"]:
            first_reg[x["id"]] = min(first_reg.get(x["id"], x["d"]), x["d"])

    def returning(x):
        return bool(x["id"]) and first_reg.get(x["id"], x["d"]) < x["d"]

    def status(x):
        if x["u"] is not None:
            return "已评分"
        if x["nq"] == 5:
            return "缺分待查"
        if x["nq"] > 0:
            return "部分作答"
        return PRE if x["d"] < launch else "Eligible Pending"

    def eligible(x):
        return status(x) != PRE

    def core_state(x):
        """True / False / UNMAPPED (Q2 or Q5 answer not in the GHL option list: needs review)."""
        if x["u"] is None or x["u"] < 70:
            return False
        if x["q2"] == UNMAPPED or x["q5"] == UNMAPPED:
            return UNMAPPED
        return (isinstance(x["q2"], (int, float)) and x["q2"] >= 20
                and isinstance(x["q5"], (int, float)) and x["q5"] >= 16)

    def is_core(x):
        return core_state(x) is True

    def pct(a, b):
        return f"{a / b * 100:.1f}%" if b else "—"

    def rm(v):
        return f"RM{v:.2f}"

    def stats(xs, spend=None, pre_ok=True, scope="同名广告"):
        # rates use Eligible as "Valid Registrations" (pre-launch rows are left out of every denominator)
        n = len(xs)
        raw = sum(x.get("raw_n", 1) for x in xs)
        el = [x for x in xs if eligible(x)]
        e = len(el)
        done = sum(1 for x in el if x["u"] is not None or x["nq"] == 5)
        q = sum(1 for x in el if x["u"] is not None and x["u"] >= 70)
        core = sum(1 for x in el if is_core(x))
        core_rv = sum(1 for x in el if core_state(x) == UNMAPPED)
        ret = [x for x in xs if returning(x)]
        ret_q = sum(1 for x in ret if eligible(x) and x["u"] is not None and x["u"] >= 70)
        ret_c = sum(1 for x in ret if eligible(x) and is_core(x))
        st = Counter(status(x) for x in xs)
        sc = [x["u"] for x in el if x["u"] is not None]
        gr = Counter(grade(u) for u in sc)
        tags = ["PRELIMINARY / INSUFFICIENT DATA" if len(sc) < min_scored else "WATCH"]
        if any(x["d"] > today - dt.timedelta(days=mature_days) for x in xs):
            tags.append(f"含最近 {mature_days} 天报名，数据未成熟")
        txt = (f"[{' · '.join(tags)}] 原始报名 {raw} 笔 · 去重后 {n} 人 · Pre-launch/邀请未知 {st[PRE]} · Valid Registrations(Eligible) {e}"
               f" · Survey Completed {done}（Completion {pct(done, e)}）· 已评分 {len(sc)}（Score Coverage {pct(len(sc), e)}）"
               f" · Eligible Pending {st['Eligible Pending']} · 部分作答 {st['部分作答']} · 缺分待查 {st['缺分待查']}"
               f" · 平均分 {f'{sum(sc) / len(sc):.1f}' if sc else '—'} · A{gr['A']} B{gr['B']} C{gr['C']} D{gr['D']}"
               f" · Qualified(≥70) {q}（÷Valid {pct(q, e)} · ÷Completed {pct(q, done)}）· Core ICP {core}"
               f"{f'（另 {core_rv} 个 {UNMAPPED}）' if core_rv else ''}"
               f" · First-time {n - len(ret)} / Returning {len(ret)}（Returning 里 Qualified {ret_q} · Core ICP {ret_c}）")
        if spend is not None:
            cpql = rm(spend / q) if q else "N/A（0 qualified）"
            txt += f" · 花费（{scope}）{rm(spend)} · CPL {rm(spend / n) if n else '—'} · {'Blended' if scope != '同名广告' else 'Preliminary'} CPQL {cpql}"
            txt += f" · 每个 Core ICP {rm(spend / core) if core else 'N/A'}"
            if not pre_ok:
                txt += "（花费区间含问卷起始日之前）"
        return txt

    # Meta spend, SG old + HK only, same date range, per ad (three names) and per day
    sp_ad, sp_day = defaultdict(float), defaultdict(float)
    res_ad, first_day = defaultdict(float), {}
    tok = result_action_type(s.meta.conversion_event)
    for _label, acct in SG_ACCTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_increment": 1,
                                                 "fields": "ad_name,adset_name,campaign_name,spend,actions",
                                                 "time_range": json.dumps({"since": d_from.isoformat(), "until": d_to.isoformat()})}):
            v = float(r.get("spend") or 0)
            sp_ad[(cpa.ad_key(r.get("campaign_name") or ""), cpa.ad_key(r.get("adset_name") or ""),
                   cpa.ad_key(r.get("ad_name") or ""))] += v
            sp_day[dt.date.fromisoformat(r["date_start"])] += v
            k3 = (cpa.ad_key(r.get("campaign_name") or ""), cpa.ad_key(r.get("adset_name") or ""),
                  cpa.ad_key(r.get("ad_name") or ""))
            res_ad[k3] += extract_results(r.get("actions"), tok)
            if v > 0:
                d0 = dt.date.fromisoformat(r["date_start"])
                first_day[k3] = min(first_day.get(k3, d0), d0)
    total_sp = sum(sp_ad.values())

    log.info("═" * 100)
    log.info("A. SG 报名 / 问卷（报名日期 %s ~ %s，读最新评分状态）· 去重口径：同一报名日期 + 同一人（姓名+电邮+电话）算 1 人，"
             "原始 %d 笔 → 去重 %d 人（去掉 %d 笔）", d_from, d_to, sum(raw_n.values()), len(sg), dups)
    post = d_from >= launch
    log.info("SG 已验证合计：%s", stats(sg, total_sp, post, "SG老户+HK 全部广告 Blended，不可跟单支广告的 CPQL 比"))
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
        log.info("   %s %s · %s", d, "一二三四五六日"[d.weekday()],
                 stats(by_day.get(d, []), sp_day.get(d, 0.0), d >= launch, "当天 SG老户+HK 全部广告 Blended"))
        d += dt.timedelta(days=1)

    log.info("═" * 100)
    log.info("B. 分数分布（SG 已验证，%s ~ %s）：%s", d_from, d_to,
             dict(Counter(grade(x["u"]) if x["u"] is not None else status(x) for x in sg)))
    log.info("   标记：有分 < %d 个 = PRELIMINARY / INSUFFICIENT DATA，≥ %d = WATCH。Qualified = 0 时 CPQL = N/A，不代表广告差；"
             "这个报告不出 SCALE / REDUCE / PAUSE，原有 CPL / CPA 规则和监控照旧", min_scored, min_scored)

    # ── C / D: by campaign, ad set, ad (spend from the same names, same dates) ───────────────────
    for lvl, n_keys in (("campaign", 1), ("ad set", 2), ("ad", 3)):
        log.info("═" * 100)
        log.info("C/D. 按 %s（%s；花费 = 同名字、同日期区间的 Meta 花费）", lvl,
                 "三层 + 只对上 campaign 的报名" if lvl == "campaign" else "只算三层都对上的报名")
        grp, names, spk, rsk = defaultdict(list), {}, defaultdict(float), defaultdict(float)
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
            rsk[hit] += res_ad.get(k3, 0.0)
            names.setdefault(hit, " / ".join(k))
        keys = sorted(set(grp) | {k for k, v in spk.items() if v > 0},
                      key=lambda k: (-sum(1 for x in grp.get(k, []) if x["u"] is not None and x["u"] >= 70), -spk.get(k, 0.0)))
        for k in keys[:30]:
            sc_list = sorted((x["u"] for x in grp.get(k, []) if x["u"] is not None), reverse=True)
            log.info("   %s · %s · Meta 平台报名 %d（只作对照，不当 Register 归因人数）· 分数 %s", names[k],
                     stats(grp.get(k, []), spk.get(k, 0.0), post), rsk.get(k, 0.0),
                     [int(u) if float(u).is_integer() else u for u in sc_list] or "—")

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
    # ── UTM retention after the survey (evidence only, no tracking-error verdict without it) ─────
    log.info("═" * 100)
    post_rows = [x for x in recs if x["d"] and x["d"] >= launch]
    surveyed = [x for x in post_rows if x["nq"] > 0 or x["u"] is not None]
    not_surv = [x for x in post_rows if not (x["nq"] > 0 or x["u"] is not None)]
    by_person = defaultdict(list)
    for x in recs:
        if x["id"]:
            by_person[x["id"]].append(x)
    no_utm_s = [x for x in surveyed if not x["J"]]
    twin = sum(1 for x in no_utm_s if any(y is not x and y["J"] for y in by_person.get(x["id"], [])))
    sg_surv = [x for x in surveyed if x["cls"] in sg_cls]
    log.info("UTM 保留检查（%s 起报名）：做了问卷 %d 行，其中带 UTM %d（%s）· 没做问卷 %d 行，其中带 UTM %d（%s）",
             launch, len(surveyed), sum(1 for x in surveyed if x["J"]), pct(sum(1 for x in surveyed if x["J"]), len(surveyed)),
             len(not_surv), sum(1 for x in not_surv if x["J"]), pct(sum(1 for x in not_surv if x["J"]), len(not_surv)))
    log.info("   做了问卷但没 UTM 的 %d 行：同一人另有带 UTM 的报名行 %d 行 · 带真实 SG 广告 UTM 又做了问卷的 %d 行（campaign + ad set + ad 都还在：%d）",
             len(no_utm_s), twin, len(sg_surv), sum(1 for x in sg_surv if x["J"] and x["K"] and x["L"]))
    utm_ok = len(sg_surv) >= min_scored
    log.info("   判断：%s", "样本够，可以看保留情况" if utm_ok else
             f"带 SG 广告 UTM 又做了问卷的只有 {len(sg_surv)} 行（< {min_scored}），证据不足，不判定 tracking error")

    # ── F: every scored / surveyed SG row in the window (row number, no personal data) ──────────
    log.info("═" * 100)
    all_sg_win = [x for x in recs if x["u"] is not None or x["nq"] > 0]
    log.info("F. 全表有问卷 / 分数的每一行（全部市场、全部日期，原始行，不去重）：%d 行 · 其中 SG %d 行", len(all_sg_win),
             sum(1 for x in all_sg_win if x["cls"] in sg_cls))
    for x in sorted(all_sg_win, key=lambda y: y["row"]):
        same = by_person.get(x["id"], []) if x["id"] else []
        cs = core_state(x)
        log.info("   第 %d 行 · 报名 %s · H %s · %s · U %s（%s）· 作答 %d/5 · Q1 %s · Q2 %s · Q3 %s · Q4 %s · Q5 %s · Core ICP %s · %s · 同一人共 %d 行（日期 %s）· UTM %r / %r / %r",
                 x["row"], x["d"], x["src"], x["cls"], x["u_raw"] or "—", grade(x["u"]) if x["u"] is not None else "无分",
                 x["nq"], x["qk"]["q1"], x["q2"], x["qk"]["q3"], x["qk"]["q4"], x["q5"],
                 "是" if cs is True else cs if cs else "否", "Returning Lead" if returning(x) else "First-time", len(same),
                 sorted({str(y["d"]) for y in same}), x["J"][:70], x["K"][:35], x["L"][:40])
        if x["u"] is not None and not (0 <= x["u"] <= 100):
            log.info("      ⚠ U 超出 0–100")
    # ── G: survey completion by registration date, every market (facts only, no cause) ─────────
    log.info("═" * 100)
    log.info("G. 每个报名日期的问卷完成情况（全部市场，原始行）：")
    d = d_from
    while d <= d_to:
        day = [x for x in recs if x["d"] == d]
        by_c = defaultdict(lambda: [0, 0, 0])
        for x in day:
            by_c[x["cls"]][0] += 1
            by_c[x["cls"]][1] += 1 if x["nq"] > 0 else 0
            by_c[x["cls"]][2] += 1 if x["u"] is not None else 0
        log.info("   %s %s · 全部 %d 行 · 有作答 %d · 有分 %d · 按归属（行 / 有作答 / 有分）%s", d, "一二三四五六日"[d.weekday()],
                 len(day), sum(1 for x in day if x["nq"] > 0), sum(1 for x in day if x["u"] is not None),
                 {c: tuple(v) for c, v in sorted(by_c.items())})
        sgd = Counter(x["J"][:70] for x in day if x["cls"] in sg_cls)
        if sgd:
            log.info("      SG 报名来自 campaign：%s", dict(sgd.most_common(6)))
        d += dt.timedelta(days=1)
    fd = sorted(((v, k) for k, v in first_day.items() if "11月新片7支" in k[0]), key=lambda z: z[0])
    if fd:
        log.info("   11月新片7支 每支广告第一天有花费（Meta 日报，%s ~ %s 内）：%s", d_from, d_to,
                 " | ".join(f"{k[2][:30]} {v}" for v, k in fd))

    # ── billing currency of the SG accounts ─────────────────────────────────────────────────────
    cur = {}
    for label, acct in SG_ACCTS:
        a = g.get_object(acct, "name,currency,account_status,timezone_name")
        cur[label] = a.get("currency")
        log.info("账户 %s %s %r：结算币种 %s · 时区 %s · 状态 %s", label, acct, a.get("name"), a.get("currency"),
                 a.get("timezone_name"), a.get("account_status"))
    cur_ok = len(set(cur.values())) == 1

    # ── computability vs decision reliability (kept apart, operator 2026-11-06) ──────────────────
    sg_post = [x for x in sg if x["d"] >= launch]
    scored_sg = sum(1 for x in sg_post if x["u"] is not None)
    q_sg = sum(1 for x in sg_post if x["u"] is not None and x["u"] >= 70)
    computable = q_sg > 0 and cur_ok
    reliab = [("SG 两个户口结算币种一致", cur_ok),
              (f"SG 已验证、起始日后报名、有分 ≥ {min_total}（现在 {scored_sg}）", scored_sg >= min_total),
              (f"带 SG 广告 UTM 又做了问卷 ≥ {min_scored}，可验证 UTM 保留（现在 {len(sg_surv)}）", utm_ok)]
    log.info("═" * 100)
    log.info("统计可计算性：Preliminary CPQL %s（起始日后 SG Qualified = %d）", "可以算" if computable else "N/A", q_sg)
    log.info("决策可靠性（只作参考，不触发任何 SCALE / REDUCE / PAUSE）：%s",
             "够" if all(c[1] for c in reliab) else "PRELIMINARY / INSUFFICIENT DATA")
    for name, ok in reliab:
        log.info("   %s %s", "✓" if ok else "✗", name)
    final_summary(log, f"{d_from}~{d_to} · SG 已验证 {stats(sg, total_sp, post)} · 币种 {cur} · CPQL "
                       f"{'可算（初步）' if computable else 'N/A'} · 决策可靠性 {'够' if all(c[1] for c in reliab) else '不足'}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
