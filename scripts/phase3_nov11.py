"""PHASE 3 — webinar_nov11 attendance × survey × sales, SG only (read-only, 12 Nov).

Operator 12 Nov brief「MARTIN SG — PHASE 3: ATTENDANCE × SURVEY × SALES VALIDATION」. Inputs: Register, Paid Student
List (RM1997), SG老户 + HK Meta insights, and the Zoom participants CSV of meeting 89007046098 passed in
ADBOT_ZOOM as salted hashes only (made on the operator's machine side: per external email, staff accounts
removed, re-entries merged, admitted minutes; email, email-local-part and name hashes). No name / email / phone
is printed; rows are shown by sheet row number and Zoom by a Z index the operator can look up locally.
Cohort = Register rows whose H (source) holds "webinar_nov11". SG = UTM campaign found on SG老户 / HK (CLAUDE.md
Lead Quality rule 8); [MY], no UTM and unverified rows are listed apart and carry no cost. Spend = SG老户 + HK,
same campaign / ad set / ad names, the cohort's registration-date range. Paid rows dated 2026-11-18 (sheet rows
1331–1335) are ignored on the operator's word. No writes anywhere.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
import lead_quality_1106 as lq  # noqa: E402  (Q2 / Q5 GHL option tables, column letters)

from adbot import cpa  # noqa: E402
from adbot.clients.sheets import SheetsClient  # noqa: E402
from adbot.commands import graph_client  # noqa: E402
from adbot.logging import final_summary, get_logger  # noqa: E402
from adbot.monitor_cpl import extract_results, result_action_type  # noqa: E402
from adbot.settings import load_settings  # noqa: E402

SG_ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
IGNORE_PAID_ROWS = set(range(1331, 1336))   # operator 12 Nov: 「無視 成交表第 1331–1335 行」


def nname(s):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s or "").casefold())


def name_keys(raw):
    out = set()
    for p in [raw] + re.findall(r"\(([^)]*)\)", raw or "") + [re.sub(r"\([^)]*\)", "", raw or "")]:
        n = nname(p)
        if n:
            out.add(n)
        toks = sorted(t for t in re.split(r"\s+", unicodedata.normalize("NFKC", p).casefold()) if re.sub(r"[\W_]+", "", t))
        if len(toks) > 1:
            out.add("|".join(re.sub(r"[\W_]+", "", t) for t in toks))
    return out


def phone_key(p):
    d = re.sub(r"\D", "", p or "")
    return d[-8:] if len(d) >= 8 else ""


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    Z = json.loads(os.environ["ADBOT_ZOOM"])
    salt = Z["salt"]
    H = lambda v: hashlib.sha256((salt + v).encode()).hexdigest()[:16]  # noqa: E731
    zoom = Z["z"]
    z_by_e, z_by_l, z_by_n = {}, defaultdict(set), defaultdict(set)
    for z in zoom:
        for h in z["e"]:
            (z_by_e.__setitem__(h, z["z"]))
        for h in z["n"]:
            z_by_n[h].add(z["z"])
    zinfo = {z["z"]: z for z in zoom}
    log.info("Zoom（会议 89007046098，已排除工作人员、合并重复进出）：%d 个外部 email · 有进到会议室的 %d · 只在等候室 %d",
             len(zoom), sum(1 for z in zoom if z["adm"]), sum(1 for z in zoom if not z["adm"]))

    sh = SheetsClient(s.secrets.google_sa_json)
    vals = sh.read_tab(s.cpa.spreadsheet_id, "Register")
    hi = next((i for i, r in enumerate(vals[:10]) if any("utm" in (c or "").lower() for c in r)), 0)
    hdr, rows = vals[hi], vals[hi + 1:]

    def find(pat, avoid=()):
        return [i for i, h in enumerate(hdr) if re.search(pat, (h or "").lower()) and i not in avoid]
    utm = {lq.idx(lq.COL[k]) for k in ("campaign", "adset", "ad")}
    e_cols, p_cols = find(r"e-?mail|电邮|電郵|邮箱"), find(r"phone|mobile|whatsapp|电话|電話|手机|手機")
    n_cols = find(r"name|姓名|名字", set(e_cols) | set(p_cols) | utm)
    log.info("Register 表头第 %d 行 · email 栏 %s · 电话栏 %s · 姓名栏 %s（只用来比对，不打印内容）", hi + 1,
             [hdr[i] for i in e_cols], [hdr[i] for i in p_cols], [hdr[i] for i in n_cols])

    def c(r, k):
        i = lq.idx(lq.COL[k])
        return (r[i] if i < len(r) else "").strip()

    def pii(r, cols):
        return [(r[i] if i < len(r) else "").strip() for i in cols]

    # Meta names (SG老户 + HK) for rule 8
    sg_ads, sg_camps = set(), set()
    for _l, acct in SG_ACCTS:
        for a in g._get_all(f"{acct}/ads", {"fields": "name,campaign{name},adset{name}", "limit": 500}):
            ck = cpa.ad_key((a.get("campaign") or {}).get("name") or "")
            sg_ads.add((ck, cpa.ad_key((a.get("adset") or {}).get("name") or ""), cpa.ad_key(a.get("name") or "")))
            sg_camps.add(ck)

    def camp_in(ck):
        return ck in sg_camps or (len(ck) >= 12 and any(p.startswith(ck) for p in sg_camps))

    def market(J):
        if not J:
            return "无 UTM"
        if camp_in(cpa.ad_key(J)):
            return "SG"
        t = lq.tag(J)
        return "MY" if t == "MY" else "SG 标记未验证" if t == "SG" else "其他"

    recs, first_reg = [], {}
    for ri, r in enumerate(rows):
        if not any((x or "").strip() for x in r):
            continue
        em = [e.lower() for e in pii(r, e_cols) if e]
        ph = {phone_key(p) for p in pii(r, p_cols)} - {""}
        nm = set().union(*[name_keys(n) for n in pii(r, n_cols) if n]) if n_cols else set()
        ident = hashlib.sha1("|".join(pii(r, n_cols + e_cols + p_cols)).lower().encode()).hexdigest()
        d = cpa.parse_date(c(r, "date"))
        if d:
            first_reg[ident] = min(first_reg.get(ident, d), d)
        recs.append({"row": hi + 2 + ri, "d": d, "src": c(r, "source"), "J": c(r, "campaign"), "K": c(r, "adset"),
                     "L": c(r, "ad"), "em": em, "ph": ph, "nm": nm, "id": ident, "u": lq.num(c(r, "score")),
                     "nq": sum(1 for q in ("q1", "q2", "q3", "q4", "q5") if c(r, q)),
                     "q2": lq.score_answer(c(r, "q2"), lq.Q2_C), "q5": lq.score_answer(c(r, "q5"), lq.Q5_C)})
    coh = [x for x in recs if "webinarnov11" in nname(x["src"])]
    log.info("webinar_nov11 报名（H 栏含 webinar_nov11）：%d 行 · H 值 %s", len(coh), dict(Counter(x["src"] for x in coh)))

    def zmatch(x):
        """exact email -> Z; else possible (email local part / name) with the reason."""
        for e in x["em"]:
            z = z_by_e.get(H("e:" + e))
            if z:
                return z, "email"
        poss = set()
        for e in x["em"]:
            loc = re.sub(r"[.\-_+]", "", e.partition("@")[0].split("+")[0])
            z = z_by_e.get(H("l:" + loc))
            if z:
                poss.add((z, "email 前缀相同、域名不同"))
        for n in x["nm"]:
            for z in z_by_n.get(H("n:" + n), ()):
                poss.add((z, "姓名相同、email 不同"))
        return None, sorted(poss)

    # one per person in the cohort (same identity = same person); keep the row with the most survey data
    best = {}
    dup_rows = 0
    for x in coh:
        if x["id"] in best:
            dup_rows += 1
            if (x["u"] is not None, x["nq"]) <= (best[x["id"]]["u"] is not None, best[x["id"]]["nq"]):
                continue
        best[x["id"]] = x
    people = list(best.values())
    for x in people:
        x["mk"] = market(x["J"])
        z, why = zmatch(x)
        x["z"], x["poss"] = (z, []) if z else (None, why)
        x["att"] = bool(z) and zinfo[z]["adm"]
        x["min"] = zinfo[z]["m"] if z else 0
        x["ret"] = first_reg.get(x["id"], x["d"]) < x["d"] if x["d"] else False
        x["done"] = x["u"] is not None
        x["qual"] = x["u"] is not None and x["u"] >= 70
        cs = (x["qual"] and isinstance(x["q2"], (int, float)) and x["q2"] >= 20
              and isinstance(x["q5"], (int, float)) and x["q5"] >= 16)
        x["core"] = True if cs else (lq.UNMAPPED if x["qual"] and lq.UNMAPPED in (x["q2"], x["q5"]) else False)
    log.info("去重后 %d 人（同一人重复报名多出 %d 行）", len(people), dup_rows)

    log.info("═" * 100)
    log.info("1. 按市场（只有 SG 算成本）：")
    for mk in ("SG", "SG 标记未验证", "MY", "无 UTM", "其他"):
        xs = [x for x in people if x["mk"] == mk]
        if not xs:
            continue
        log.info("   %-8s 报名 %d · 出席(email 精确) %d · 已评分 %d（出席 %d）· Qualified %d · Core %d · Returning %d", mk, len(xs),
                 sum(x["att"] for x in xs), sum(x["done"] for x in xs), sum(x["att"] for x in xs if x["done"]),
                 sum(x["qual"] for x in xs), sum(x["core"] is True for x in xs), sum(x["ret"] for x in xs))
    sg = [x for x in people if x["mk"] == "SG"]

    log.info("═" * 100)
    log.info("2. SG 每一位报名（只列行号，不列个资）：")
    for x in sorted(sg, key=lambda x: (not x["done"], x["row"])):
        log.info("   第 %d 行 · 报名 %s · %s · 分数 %s · Q2 %s · Q5 %s · Core %s · %s · 出席 %s%s · ad %r / ad set %r",
                 x["row"], x["d"], "Returning" if x["ret"] else "First-time",
                 int(x["u"]) if x["u"] is not None else ("Pending" if not x["nq"] else f"部分作答{x['nq']}/5"),
                 x["q2"], x["q5"], x["core"], "问卷完成" if x["done"] else "未完成",
                 f"✔ {x['z']}（{x['min']} 分钟，{zinfo[x['z']]['j']} 进）" if x["att"] else "✘",
                 f" · 可能对得上：{x['poss']}" if x["poss"] else "", x["L"][:40], x["K"][:30])

    log.info("═" * 100)
    log.info("3. SG 问卷完成 vs 未完成 的出席：")
    for lbl, xs in (("问卷完成", [x for x in sg if x["done"]]), ("未完成 / Pending", [x for x in sg if not x["done"]])):
        att = [x for x in xs if x["att"]]
        log.info("   %s：%d 人 · 出席 %d · 出席率 %s · 出席者平均在线 %s 分钟 · 另有「可能对得上」%d 人", lbl, len(xs), len(att),
                 f"{len(att) / len(xs) * 100:.1f}%" if xs else "—",
                 f"{sum(x['min'] for x in att) / len(att):.0f}" if att else "—", sum(1 for x in xs if x["poss"] and not x["att"]))

    # Meta spend, SG老户 + HK, the cohort's registration-date range
    ds = [x["d"] for x in sg if x["d"]]
    d_from, d_to = min(ds), max(ds)
    tok = result_action_type(s.meta.conversion_event)
    sp, mr = defaultdict(float), defaultdict(float)
    for _l, acct in SG_ACCTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_name,adset_name,campaign_name,spend,actions",
                                                 "time_range": json.dumps({"since": d_from.isoformat(), "until": d_to.isoformat()})}):
            k = (cpa.ad_key(r.get("campaign_name") or ""), cpa.ad_key(r.get("adset_name") or ""), cpa.ad_key(r.get("ad_name") or ""))
            sp[k] += float(r.get("spend") or 0)
            mr[k] += extract_results(r.get("actions"), tok)
    names = {}

    def key(x):
        k = (cpa.ad_key(x["J"]), cpa.ad_key(x["K"]), cpa.ad_key(x["L"]))
        if k in sp:
            return k
        hit = [m for m in sp if m[1] == k[1] and m[2] == k[2] and len(k[0]) >= 12 and m[0].startswith(k[0])]
        return hit[0] if hit else k
    grp = defaultdict(list)
    for x in sg:
        k = key(x)
        grp[k].append(x)
        names[k] = (x["J"], x["K"], x["L"])

    def rm(v):
        return f"RM{v:.2f}"

    def line(xs, spend):
        n, a, q = len(xs), sum(x["att"] for x in xs), sum(x["qual"] for x in xs)
        return (f"报名 {n} · 出席 {a} · 已评分 {sum(x['done'] for x in xs)} · Qualified {q} · Core {sum(x['core'] is True for x in xs)}"
                f" · Returning {sum(x['ret'] for x in xs)} · 花费 {rm(spend)} · CPL {rm(spend / n) if n else '—'}"
                f" · 每个出席 {rm(spend / a) if a else 'N/A（0 出席）'} · Preliminary CPQL {rm(spend / q) if q else 'N/A（0 qualified）'}")
    log.info("═" * 100)
    log.info("4/5. SG 按 campaign / ad set / ad（花费 = SG老户 + HK 同名广告 %s ~ %s）：", d_from, d_to)
    for k, xs in sorted(grp.items(), key=lambda kv: -len(kv[1])):
        J, K, L = names[k]
        log.info("   campaign %r › ad set %r › ad %r", J[:70], K[:35], L[:45])
        log.info("      %s · Meta 报名 %.0f", line(xs, sp.get(k, 0.0)), mr.get(k, 0.0))
    by_c = defaultdict(list)
    for x in sg:
        by_c[key(x)[0]].append(x)
    log.info("   按 campaign：")
    for ck, xs in sorted(by_c.items(), key=lambda kv: -len(kv[1])):
        log.info("      %r · %s", xs[0]["J"][:70], line(xs, sum(v for k, v in sp.items() if k[0] == ck)))
    no_lead = sum(v for k, v in sp.items() if k not in grp and v > 0)
    total = sum(sp.values())
    log.info("   SG 合计（Blended，SG老户 + HK 全部花费 %s；其中没有 webinar_nov11 报名的广告花了 %s）：%s", rm(total), rm(no_lead),
             line(sg, total))

    log.info("═" * 100)
    log.info("6. Paid Student List：")
    pv = sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    ph_i, cols = 0, cpa.find_columns(pv[0])
    for i, r in enumerate(pv[:8]):
        cc = cpa.find_columns(r)
        if cc.get("campaign", -1) >= 0 and cc.get("ad", -1) >= 0:
            ph_i, cols = i, cc
            break
    phd = pv[ph_i]
    pe = [i for i, h in enumerate(phd) if re.search(r"e-?mail|电邮|電郵|邮箱", (h or "").lower())]
    pp = [i for i, h in enumerate(phd) if re.search(r"phone|mobile|whatsapp|电话|電話|手机|手機", (h or "").lower())]
    log.info("   成交表 email 栏 %s · 电话栏 %s", [phd[i] for i in pe], [phd[i] for i in pp])
    sg_ids = {}
    for x in people:
        for e in x["em"]:
            sg_ids[("e", e)] = x
        for p in x["ph"]:
            sg_ids[("p", p)] = x

    def pc(r, k):
        j = cols.get(k, -1)
        return (r[j] if 0 <= j < len(r) else "").strip()
    for n, r in enumerate(pv[ph_i + 1:], start=ph_i + 2):
        if not any((v or "").strip() for v in r):
            continue
        d = cpa.parse_date(pc(r, "date"))
        ids = [("e", (r[i] if i < len(r) else "").strip().lower()) for i in pe] + \
              [("p", phone_key(r[i] if i < len(r) else "")) for i in pp]
        hit = next((sg_ids[k] for k in ids if k[1] and k in sg_ids), None)
        recent = d and d >= dt.date(2026, 11, 11)
        if not (recent or hit):
            continue
        if n in IGNORE_PAID_ROWS:
            log.info("   第 %d 行（%s）：operator 说无视，跳过", n, d)
            continue
        log.info("   第 %d 行 · 日期 %s · 成交 UTM 市场 %s · UTM ad %r · 对上 webinar_nov11 报名：%s", n, d, market(pc(r, "campaign")),
                 pc(r, "ad")[:40], f"第 {hit['row']} 行（报名 UTM 市场 {hit['mk']}，出席 {'✔' if hit['att'] else '✘'}，"
                 f"分数 {int(hit['u']) if hit['u'] is not None else 'Pending'}）" if hit else "没有")

    log.info("═" * 100)
    log.info("7. Zoom email 对不上 webinar_nov11 报名的：")
    matched = {x["z"] for x in people if x["z"]}
    all_e = {}
    for x in recs:
        for e in x["em"]:
            all_e[H("e:" + e)] = x
    for z in zoom:
        if z["z"] in matched:
            continue
        other = next((all_e[h] for h in z["e"] if h in all_e), None)
        alias = sorted({x["row"] for x in people for nkey in x["nm"] if z["z"] in z_by_n.get(H("n:" + nkey), ())})
        log.info("   %s · 在线 %s 分钟 · %s · 同名的 nov11 报名行：%s", z["z"], z["m"],
                 f"email 在 Register 别的报名（第 {other['row']} 行，H={other['src']!r}，{other['d']}，UTM 市场 {market(other['J'])}）"
                 if other else "email 不在 Register", alias or "没有")
    final_summary(log, f"webinar_nov11 SG {len(sg)} 人 · 出席 {sum(x['att'] for x in sg)} · 已评分 {sum(x['done'] for x in sg)}"
                       f"（出席 {sum(x['att'] for x in sg if x['done'])}）· Qualified {sum(x['qual'] for x in sg)} · SG 花费 {rm(total)}")


if __name__ == "__main__":
    main()
