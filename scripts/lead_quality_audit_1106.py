"""MARTIN SG — Lead Quality Phase 1 read-only audit (6 Nov).

Register tab only (A–U). Personal columns (A name, B phone, C email) are never printed: they are used
only to flag rows containing "test" and to count repeat registrations (hashed in memory).
SG attribution, strongest first:
  L1 已验证 SG   UTM campaign (J) equals (or is a cut-off prefix of) a campaign on SG old
                 act_1024930575770087 or HK act_1179668409969241 whose ad sets all target Singapore only.
  L1x 账户内但不是只投 SG   campaign found on those accounts but some ad set targets another country.
  L2 [SG] 标记未验证   J carries [SG] / martin-sg but no such campaign on either account.
  MY            J carries [MY] / martin-my / " MY " markers -> excluded.
  W  只有 ad set + ad 名字   J empty, K + L equal an SG-only ad on the two accounts -> reported, NOT counted.
  U  来源不明    everything else.
Survey: columns P–T (Q1–Q5) and U (score) — fill rates, and if any are filled, A/B/C/D, High Score,
Core ICP (U >= 70, Q2 >= 20, Q5 >= 16, Q2/Q5 scored from the raw answer text). No writes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

TAB = "Register"
ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
G, H, J, K, L = 6, 7, 9, 10, 11
P, Q, R, S, T, U = 15, 16, 17, 18, 19, 20
Q2_SCORE = [("身高记录", 25), ("成长变慢", 25), ("成长评估", 25), ("比同龄", 20), ("矮", 20), ("不确定", 12),
            ("提前学习", 5)]
Q5_SCORE = [("专业指导", 20), ("持续跟进", 20), ("系统性", 16), ("按步骤", 16), ("先了解", 10), ("免费资讯", 4),
            ("免费", 4)]


def cell(r, i):
    return str(r[i]).strip() if i < len(r) else ""


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def score_text(txt, table):
    t = txt or ""
    for k, v in table:
        if k in t:
            return v
    return None


def grade(v):
    return "A" if v >= 85 else "B" if v >= 70 else "C" if v >= 50 else "D"


def is_my(c):
    n = cpa.norm(c)
    return "[my]" in n or "martin-my" in n or "martin my" in n or " my " in f" {n} " or n.startswith("my ")


def is_sg_tag(c):
    n = cpa.norm(c)
    return "[sg]" in n or "martin-sg" in n or "martin sg" in n


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    yday = today - dt.timedelta(days=1)
    d30 = today - dt.timedelta(days=30)
    cyc0 = dt.date.fromisoformat(os.environ.get("ADBOT_CYCLE_FROM") or "2026-11-05")
    sh = SheetsClient(s.secrets.google_sa_json)
    meta = sh._svc.spreadsheets().get(spreadsheetId=s.cpa.spreadsheet_id,
                                      fields="sheets.properties(title,gridProperties)").execute()
    log.info("试算表所有分页（只列名字和大小）：")
    for x in meta.get("sheets", []):
        p = x["properties"]
        log.info("   %r · %s 行 × %s 栏", p["title"], (p.get("gridProperties") or {}).get("rowCount"),
                 (p.get("gridProperties") or {}).get("columnCount"))
    rows = sh.read_tab(s.cpa.spreadsheet_id, TAB)
    hdr, data = rows[0], rows[1:]
    log.info("Register：数据 %d 行 · 表头 %s", len(data), {chr(65 + i): h for i, h in enumerate(hdr)})

    # ── Meta: SG-only campaigns on the two accounts ─────────────────────────────────────────────
    camp_geo = defaultdict(set)                       # campaign id -> countries targeted by its ad sets
    camp_name, camp_acct = {}, {}
    ad_keys = defaultdict(set)                        # (adset key, ad key) -> campaign ids
    full_keys = set()
    def every(path, fields, statuses):                # include paused + archived, fall back to the default list
        try:
            return g._get_all(path, {"fields": fields, "limit": 500, "effective_status": json.dumps(statuses)})
        except TransientGraphError:
            raise
        except GraphError as exc:
            log.info("（%s 不能按 effective_status 读，改读默认列表：%s）", path, str(exc)[:120])
            return g._get_all(path, {"fields": fields, "limit": 500})

    base_st = ["ACTIVE", "PAUSED", "ARCHIVED", "IN_PROCESS", "WITH_ISSUES"]
    for label, acct in ACCTS:
        for st in every(f"{acct}/adsets", "id,campaign_id,targeting", base_st + ["CAMPAIGN_PAUSED"]):
            geo = ((st.get("targeting") or {}).get("geo_locations") or {})
            countries = set(geo.get("countries") or [])
            for loc in (geo.get("regions") or []) + (geo.get("cities") or []):
                if loc.get("country"):
                    countries.add(loc["country"])
            camp_geo[st.get("campaign_id")] |= countries or {"?"}
        for c in every(f"{acct}/campaigns", "id,name", base_st):
            camp_name[c["id"]] = c.get("name") or ""
            camp_acct[c["id"]] = label
        for a in every(f"{acct}/ads", "name,campaign{id},adset{name}",
                       base_st + ["CAMPAIGN_PAUSED", "ADSET_PAUSED", "DISAPPROVED", "PENDING_REVIEW"]):
            cid = (a.get("campaign") or {}).get("id")
            sk, ak = cpa.ad_key((a.get("adset") or {}).get("name") or ""), cpa.ad_key(a.get("name") or "")
            ad_keys[(sk, ak)].add(cid)
            full_keys.add((cpa.ad_key(camp_name.get(cid, "")), sk, ak))
    sg_only = {cid for cid in camp_name if camp_geo.get(cid) == {"SG"}}
    by_ckey = defaultdict(set)
    for cid, n in camp_name.items():
        by_ckey[cpa.ad_key(n)].add(cid)
    log.info("SG老户 + HK：campaign %d 个 · 只投新加坡的 %d 个 · 其他国家 / 混投 %d 个 · 投放国家分布 %s",
             len(camp_name), len(sg_only), len(camp_name) - len(sg_only),
             Counter(",".join(sorted(v)) for v in camp_geo.values()).most_common(8))

    def find_campaign(j):
        k = cpa.ad_key(j)
        if not k:
            return set()
        if k in by_ckey:
            return by_ckey[k]
        if len(k) >= 12:                              # the sheet cuts long names
            return {cid for ck, ids in by_ckey.items() if ck.startswith(k) for cid in ids}
        return set()

    # ── classify rows ───────────────────────────────────────────────────────────────────────────
    seen_contact = Counter()
    out = []
    for n, r in enumerate(data):
        rowno = n + 2
        if not any(cell(r, i) for i in range(len(r))):
            continue
        pers = " ".join(cell(r, i) for i in (0, 1, 2)).casefold()
        test = "test" in pers
        contact = hashlib.sha1((cell(r, 1)[-8:] + "|" + cell(r, 2).casefold()).encode()).hexdigest()
        j, k, l = cell(r, J), cell(r, K), cell(r, L)
        cids = find_campaign(j) if j else set()
        if j and is_my(j):
            lvl = "MY"
        elif cids and cids <= sg_only:
            lvl = "L1"
        elif cids:
            lvl = "L1x"
        elif j and is_sg_tag(j):
            lvl = "L2"
        elif not j and k and l and ad_keys.get((cpa.ad_key(k), cpa.ad_key(l))) and \
                ad_keys[(cpa.ad_key(k), cpa.ad_key(l))] <= sg_only:
            lvl = "W"
        else:
            lvl = "U"
        out.append({"row": rowno, "date": cpa.parse_date(cell(r, G)), "src": cell(r, H), "j": j, "k": k, "l": l,
                    "lvl": lvl, "test": test, "contact": contact,
                    "full": (cpa.ad_key(j), cpa.ad_key(k), cpa.ad_key(l)) in full_keys if lvl == "L1" else False,
                    "q": [cell(r, i) for i in (P, Q, R, S, T)], "u": num(cell(r, U)), "u_raw": cell(r, U)})
        if lvl in ("L1", "L2", "W"):
            seen_contact[contact] += 1

    names = {"L1": "已验证 SG", "L1x": "账户内但不是只投 SG", "L2": "[SG] 标记未验证", "MY": "MY（排除）",
             "W": "J 空，只有 ad set + ad 名字对上 SG 广告（不计入）", "U": "来源不明"}

    def tally(rs, title):
        c = Counter(x["lvl"] for x in rs)
        log.info("%s：共 %d 行 · %s", title, len(rs), " · ".join(f"{names[k]} {c.get(k, 0)}" for k in names))

    log.info("═" * 100)
    tests = [x["row"] for x in out if x["test"]]
    log.info("疑似内部测试（姓名 / 电话 / email 含 'test'）%d 行 · 行号 %s · 下面的数字都已排除这些行", len(tests), tests)
    rs = [x for x in out if not x["test"]]
    nodate = [x for x in rs if not x["date"]]
    log.info("日期读不出的行 %d（G 栏空或格式不对）", len(nodate))
    tally(rs, "全部")
    tally([x for x in rs if x["date"] and x["date"] >= d30], f"近 30 天（{d30}~{today}）")
    tally([x for x in rs if x["date"] and x["date"] >= cyc0], f"本期（{cyc0}~{today}）")
    tally([x for x in rs if x["date"] == yday], f"昨天（{yday}）")
    tally([x for x in rs if x["date"] == today], f"今天（{today}，未完）")

    log.info("═" * 100)
    log.info("每天报名（已验证 SG / [SG] 未验证 / 只有名字 / 来源不明 / MY）近 14 天：")
    for i in range(13, -1, -1):
        d = today - dt.timedelta(days=i)
        c = Counter(x["lvl"] for x in rs if x["date"] == d)
        log.info("   %s %s · 已验证 SG %d · [SG] 未验证 %d · 只有名字 %d · 来源不明 %d · MY %d", d, "一二三四五六日"[d.weekday()],
                 c["L1"], c["L2"], c["W"], c["U"], c["MY"])

    # ── survey / score ──────────────────────────────────────────────────────────────────────────
    log.info("═" * 100)
    sg = [x for x in rs if x["lvl"] == "L1"]
    for label, part in (("全部已验证 SG", sg), ("近 30 天已验证 SG", [x for x in sg if x["date"] and x["date"] >= d30]),
                        ("昨天已验证 SG", [x for x in sg if x["date"] == yday])):
        qf = [sum(1 for x in part if x["q"][i]) for i in range(5)]
        uf = sum(1 for x in part if x["u_raw"])
        un = sum(1 for x in part if x["u"] is not None)
        allq = sum(1 for x in part if all(x["q"]))
        log.info("%s %d 行 · Q1~Q5 有值 %s · 五题都有 %d · U 有值 %d（其中是数字 %d）", label, len(part), qf, allq, uf, un)
    scored = [x for x in sg if x["u"] is not None]
    if scored:
        gc = Counter(grade(x["u"]) for x in scored)
        hi = [x for x in scored if x["u"] >= 70]
        core, unk = [], 0
        for x in hi:
            q2, q5 = score_text(x["q"][1], Q2_SCORE), score_text(x["q"][4], Q5_SCORE)
            if q2 is None or q5 is None:
                unk += 1
            elif q2 >= 20 and q5 >= 16:
                core.append(x)
        log.info("评分：A %d · B %d · C %d · D %d · High Score %d · Core ICP %d · Q2/Q5 答案对不上评分表 %d",
                 gc["A"], gc["B"], gc["C"], gc["D"], len(hi), len(core), unk)
    else:
        log.info("评分：已验证 SG 里没有任何一行有 U 栏分数 → A/B/C/D、High Score、Core ICP 都算不出来")
    for i, h in ((12, "M"), (13, "N"), (14, "O")):
        vals = Counter(cell(data[x["row"] - 2], i)[:40] for x in sg if cell(data[x["row"] - 2], i))
        log.info("旧问卷栏 %s %r · 已验证 SG 有值 %d 行 · 前 8：%s", h, hdr[i] if i < len(hdr) else "",
                 sum(vals.values()), vals.most_common(8))

    # ── per SG campaign / ad set / ad, last 30 days ─────────────────────────────────────────────
    log.info("═" * 100)
    s30 = [x for x in sg if x["date"] and x["date"] >= d30]
    log.info("近 30 天已验证 SG %d 行 · 三个 UTM 都对上现有广告 %d · 缺 ad set %d · 缺 ad %d", len(s30),
             sum(1 for x in s30 if x["full"]), sum(1 for x in s30 if not x["k"]), sum(1 for x in s30 if not x["l"]))
    per = Counter((x["j"][:60], x["k"][:35], x["l"][:40], x["full"]) for x in s30)
    for (j, k, l, f), n in per.most_common(40):
        log.info("   %4d · %s · campaign %r · ad set %r · ad %r", n, "对上" if f else "对不上", j, k, l)
    log.info("近 30 天 [SG] 标记但账户内找不到的 campaign：%s",
             Counter(x["j"][:70] for x in rs if x["lvl"] == "L2" and x["date"] and x["date"] >= d30).most_common(10))
    log.info("近 30 天来源不明的 J 值（前 10，空 = J 栏空）：%s",
             Counter(x["j"][:60] for x in rs if x["lvl"] == "U" and x["date"] and x["date"] >= d30).most_common(10))
    log.info("近 30 天 L1x（账户内但不是只投 SG）：%s",
             Counter(x["j"][:60] for x in rs if x["lvl"] == "L1x" and x["date"] and x["date"] >= d30).most_common(10))
    log.info("近 30 天已验证 SG 的 H 栏 source：%s", Counter(x["src"][:40] for x in s30).most_common(10))
    rep = sum(1 for v in seen_contact.values() if v > 1)
    log.info("SG（已验证 + 未验证 + 只有名字）同一电话尾 8 位 + email 重复报名：%d 个联系人重复，多出 %d 行", rep,
             sum(v - 1 for v in seen_contact.values() if v > 1))
    c30 = Counter(x["lvl"] for x in rs if x["date"] and x["date"] >= d30)
    base = sum(c30.values())
    final_summary(log, f"Register {len(out)} 行 · 疑似测试 {len(tests)} · 近 30 天 {base} 行：已验证 SG {c30['L1']} · "
                       f"[SG] 未验证 {c30['L2']} · 只有名字 {c30['W']} · 来源不明 {c30['U']} · MY {c30['MY']} · "
                       f"有分数的已验证 SG {len(scored)}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
