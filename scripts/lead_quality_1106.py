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
"""
from __future__ import annotations

import datetime as dt
import hashlib
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
    yday = today - dt.timedelta(days=1)

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

    # ── SG scope ────────────────────────────────────────────────────────────────────────────────
    sg_cls = ("SG✔ 三层", "SG✔ campaign")
    win = [x for x in recs if x["d"] and start and x["d"] >= start]

    def summary(label, xs):
        n = len(xs)
        full = sum(1 for x in xs if x["nq"] == 5)
        part = sum(1 for x in xs if 0 < x["nq"] < 5)
        scored = [x for x in xs if x["u"] is not None]
        miss = sum(1 for x in xs if x["nq"] > 0 and x["u"] is None)
        gr = Counter(grade(x["u"]) for x in scored)
        hi_ = [x for x in scored if x["u"] >= 70]
        core = [x for x in hi_ if isinstance(x["q2"], (int, float)) and x["q2"] >= 20
                and isinstance(x["q5"], (int, float)) and x["q5"] >= 16]
        unk = sum(1 for x in hi_ if not isinstance(x["q2"], (int, float)) or not isinstance(x["q5"], (int, float)))
        avg = sum(x["u"] for x in scored) / len(scored) if scored else None
        log.info("%s：报名 %d · 问卷 5 题全答 %d（%s）· 只答部分 %d · 有分 %d · 有答题没分 %d · 平均分 %s · A %d B %d C %d D %d · "
                 "高分(≥70) %d（占有分 %s）· Core ICP %d（占有分 %s）· 高分但 Q2/Q5 对不上表 %d",
                 label, n, full, f"{full / n * 100:.1f}%" if n else "—", part, len(scored), miss,
                 f"{avg:.1f}" if avg is not None else "—", gr["A"], gr["B"], gr["C"], gr["D"], len(hi_),
                 f"{len(hi_) / len(scored) * 100:.1f}%" if scored else "—", len(core),
                 f"{len(core) / len(scored) * 100:.1f}%" if scored else "—", unk)
        return {"n": n, "full": full, "scored": len(scored), "hi": len(hi_), "core": len(core), "avg": avg, "gr": gr}

    log.info("═" * 100)
    log.info("A. 报名 / 问卷（%s 起，按报名日期）", start)
    for c in ("SG✔ 三层", "SG✔ campaign", "SG 标记未验证", "冲突", "MY", "无 UTM", "其他"):
        summary(c, [x for x in win if x["cls"] == c])
    sg = [x for x in win if x["cls"] in sg_cls]
    summary("SG 已验证合计（三层 + campaign）", sg)
    log.info("按报名日期（SG 已验证）——同一批报名后来做了问卷的人数：")
    by_day = defaultdict(list)
    for x in sg:
        by_day[x["d"]].append(x)
    for d in sorted(by_day)[-21:]:
        xs = by_day[d]
        log.info("   %s %s · 报名 %d · 已全答 %d · 有分 %d · 高分 %d", d, "一二三四五六日"[d.weekday()], len(xs),
                 sum(1 for x in xs if x["nq"] == 5), sum(1 for x in xs if x["u"] is not None),
                 sum(1 for x in xs if x["u"] is not None and x["u"] >= 70))
    log.info("昨天 %s：SG 已验证报名 %d · 其中已经有分 %d（问卷提交日期表上没有的话，'昨天提交问卷人数' 算不出）",
             yday, len(by_day.get(yday, [])), sum(1 for x in by_day.get(yday, []) if x["u"] is not None))

    # ── B: distribution across cycles ───────────────────────────────────────────────────────────
    log.info("═" * 100)
    log.info("B. 分数分布（SG 已验证，按直播周期 星期四~星期二）")
    cyc = defaultdict(list)
    for x in sg:
        thu = x["d"] - dt.timedelta(days=(x["d"].weekday() - 3) % 7)
        cyc[thu].append(x)
    for thu in sorted(cyc):
        summary(f"   周期 {thu}~{thu + dt.timedelta(days=5)}（直播 {thu + dt.timedelta(days=6)}）", cyc[thu])

    # ── C / D: by campaign, ad set, ad ──────────────────────────────────────────────────────────
    for lvl, keyf in (("campaign", lambda x: (x["J"],)), ("ad set", lambda x: (x["J"], x["K"])),
                      ("ad", lambda x: (x["J"], x["K"], x["L"]))):
        log.info("═" * 100)
        log.info("C/D. 按 %s（只算三层都对上的 SG 报名；按高分人数排）", lvl)
        grp = defaultdict(list)
        for x in sg:
            if x["cls"] == "SG✔ 三层" or lvl == "campaign":
                grp[keyf(x)].append(x)
        def stats(xs):
            sc = [x for x in xs if x["u"] is not None]
            h = [x for x in sc if x["u"] >= 70]
            core = [x for x in h if isinstance(x["q2"], (int, float)) and x["q2"] >= 20
                    and isinstance(x["q5"], (int, float)) and x["q5"] >= 16]
            return sc, h, core
        ranked = sorted(grp.items(), key=lambda kv: (-len(stats(kv[1])[1]), -len(kv[1])))
        for k, xs in ranked[:25]:
            sc, h, core = stats(xs)
            gr = Counter(grade(x["u"]) for x in sc)
            log.info("   %s · 报名 %d · 有分 %d · 平均 %s · A%d B%d C%d D%d · 高分 %d（%s）· Core ICP %d（%s）",
                     " / ".join(v[:55] for v in k), len(xs), len(sc),
                     f"{sum(x['u'] for x in sc) / len(sc):.1f}" if sc else "—", gr["A"], gr["B"], gr["C"], gr["D"],
                     len(h), f"{len(h) / len(sc) * 100:.0f}%" if sc else "—", len(core),
                     f"{len(core) / len(sc) * 100:.0f}%" if sc else "—")

    # ── E: attribution ──────────────────────────────────────────────────────────────────────────
    log.info("═" * 100)
    tagged = [x for x in win if tag(x["J"]) == "SG" or x["cls"] in sg_cls]
    log.info("E. 归因：%s 起带 [SG] 或对上 SG 户口的报名 %d · 三层对上 %d · 只对上 campaign %d · 带 [SG] 但户口里没有 %d · 冲突 %d",
             start, len(tagged), sum(1 for x in tagged if x["cls"] == "SG✔ 三层"),
             sum(1 for x in tagged if x["cls"] == "SG✔ campaign"), sum(1 for x in tagged if x["cls"] == "SG 标记未验证"),
             sum(1 for x in tagged if x["cls"] == "冲突"))
    for c in ("SG✔ campaign", "SG 标记未验证", "冲突", "其他"):
        top = Counter((x["J"][:60], x["K"][:30], x["L"][:35]) for x in win if x["cls"] == c).most_common(8)
        if top:
            log.info("   %s 最常见的 UTM（campaign / ad set / ad）：", c)
            for k, n in top:
                log.info("      %3d × %s", n, " / ".join(repr(v) for v in k))
    final_summary(log, f"Register {len(recs)} 行（测试排除 {sum(tests.values())}）· 问卷起 {start} · SG 已验证 {len(sg)} · "
                       f"归属 {dict(Counter(x['cls'] for x in win))}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
