"""Read-only audit: yesterday's paid sales + which CONVERTING ads are currently OFF.

1) Yesterday's new paid enrolments from the Paid Student List (ad name / ad set / amount).
2) Scan the WHOLE SG account (ACTIVE and PAUSED ads). For every ad NAME that has paid sales
   (yesterday / 7d / 30d / lifetime), show whether a LIVE ad by that name is still running.
   Flag the ones that convert but have NO active ad — split by WHY they're off:
     🔴 ad-level PAUSED  → the ad itself was switched off (monitor auto-pause / manual) — reactivate candidate
     🟡 campaign/adset off → structural (new PAUSED build, weekly OFF) — activate the container to run it
     ⚪ not in SG account → sold under this creative name but no SG ad (likely MY-only creative)

Sales are matched by ad NAME (width/punctuation-robust ad_key), campaign-agnostic. The sheet
is shared with MY, so a name's sale count can include MY sales — treat counts as a
"this creative converts" signal, and the FOCUS is: is a converting creative live in SG or not.
Writes nothing.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.settings import load_settings

DATE_HDRS = ("报名日期", "報名日期", "date", "日期", "报名", "報名", "成交日期", "付款日期", "购买日期")
CAMP_HDRS = ("utm campaign", "campaign name", "campaign", "广告系列", "廣告系列", "活动", "活動")


def _hkey(x: str) -> str:
    return (x or "").strip().lower()


def _find_col(header, needles) -> int:
    keys = [_hkey(h) for h in header]
    for n in needles:
        for i, k in enumerate(keys):
            if n in k:
                return i
    return -1


def _sniff_date_col(rows, hdr_idx, ncols) -> int:
    best, best_hits = -1, 0
    for c in range(ncols):
        hits = sum(1 for row in rows[hdr_idx + 1: hdr_idx + 81]
                   if c < len(row) and cpa.parse_date(row[c]))
        if hits > best_hits:
            best, best_hits = c, hits
    return best if best_hits >= 10 else -1


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()   # MYT
    yday = today - dt.timedelta(days=1)

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)

    # header row = first row exposing a UTM ad + ad set column
    hdr_idx, cols = 0, cpa.find_columns(values[0] if values else [])
    for i, row in enumerate(values[:8]):
        c = cpa.find_columns(row)
        if c.get("ad", -1) >= 0 and c.get("adset", -1) >= 0:
            hdr_idx, cols = i, c
            break
    header = values[hdr_idx]
    ncols = max((len(r) for r in values[hdr_idx:hdr_idx + 60]), default=0)
    ad_col, adset_col, amt_col = cols.get("ad", 15), cols.get("adset", 14), cols.get("amount", 7)
    date_col = cols.get("date", -1)
    if date_col < 0:
        date_col = _find_col(header, DATE_HDRS)
    if date_col < 0:
        date_col = _sniff_date_col(values, hdr_idx, ncols)

    def cell(row, i):
        return row[i] if 0 <= i < len(row) else ""

    # ── tally sales by ad NAME across windows + collect yesterday's rows ─────────
    win = defaultdict(lambda: {"y": 0, "7d": 0, "30d": 0, "life": 0})
    yrows = []
    for row in values[hdr_idx + 1:]:
        ad = cpa.norm(cell(row, ad_col))
        key = cpa.ad_key(cell(row, ad_col))
        if not key:
            continue
        d = cpa.parse_date(cell(row, date_col)) if date_col >= 0 else None
        w = win[key]
        w["life"] += 1
        w["_name"] = ad
        if d:
            if d > today - dt.timedelta(days=30):
                w["30d"] += 1
            if d > today - dt.timedelta(days=7):
                w["7d"] += 1
            if d == yday:
                w["y"] += 1
                yrows.append((ad, cpa.norm(cell(row, adset_col)),
                              cpa._money(cell(row, amt_col), s.cpa.price_myr)))

    # ── every ad in the SG account (ACTIVE + PAUSED), indexed by ad_key(name) ────
    g = graph_client(s)
    acct = s.meta.account_path
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,effective_status,campaign{name},adset{name}", "limit": 500})
    by_key = defaultdict(list)
    for a in ads:
        by_key[cpa.ad_key(a.get("name", ""))].append({
            "id": a["id"], "name": a.get("name", ""), "status": a.get("effective_status", "?"),
            "camp": (a.get("campaign") or {}).get("name", "∅"),
            "adset": (a.get("adset") or {}).get("name", "∅")})

    def status_of(key):
        rows = by_key.get(key, [])
        if any(r["status"] == "ACTIVE" for r in rows):
            return "ACTIVE", rows
        if not rows:
            return "ABSENT", rows
        # off: pick the most informative single reason
        st = {r["status"] for r in rows}
        if "PAUSED" in st:
            return "AD_PAUSED", rows
        return "CONTAINER_OFF", rows   # ADSET_PAUSED / CAMPAIGN_PAUSED / ARCHIVED

    print(f"Sales × Ads-Manager audit — today MYT={today} · yesterday={yday}")
    print(f"sheet tab={s.cpa.sales_tab!r} · header row #{hdr_idx} · "
          f"cols date={date_col} ad={ad_col} adset={adset_col} amt={amt_col}\n")

    # ── SECTION A: yesterday's new sales ────────────────────────────────────────
    rev = sum(a for _, _, a in yrows)
    print("═" * 90)
    print(f" A. 昨天新成交 ({yday}): {len(yrows)} 单 · 收入 RM{rev:,.0f}")
    print("═" * 90)
    yby = defaultdict(lambda: [0, 0.0, ""])
    for ad, adset, amt in yrows:
        e = yby[cpa.ad_key(ad)]
        e[0] += 1
        e[1] += amt
        e[2] = ad
    for key, (n, amt, name) in sorted(yby.items(), key=lambda kv: -kv[1][0]):
        stt, rows = status_of(key)
        tag = {"ACTIVE": "▶ 在跑", "AD_PAUSED": "⏸ 广告被关", "CONTAINER_OFF": "⏸ 系列/组 关着",
               "ABSENT": "— 不在SG账户"}[stt]
        where = f" · {rows[0]['camp'][:34]}" if rows else ""
        print(f"  {n}单 RM{amt:>6,.0f}  {tag:12}  {name[:40]!r}{where}")
    if not yrows:
        print("  (昨天这个 tab 没有新成交行)")

    # ── SECTION B: converting but OFF (the main ask) ────────────────────────────
    ad_paused, container_off, absent = [], [], []
    for key, w in win.items():
        stt, rows = status_of(key)
        if stt == "ACTIVE":
            continue
        item = (w, rows)
        if stt == "AD_PAUSED":
            ad_paused.append(item)
        elif stt == "CONTAINER_OFF":
            container_off.append(item)
        else:
            absent.append(item)

    def _key(it):
        w = it[0]
        return (-w["30d"], -w["7d"], -w["life"])

    def _line(w, rows):
        nm = w.get("_name", "∅")
        loc = "; ".join(sorted({f"{r['camp'][:30]} [{r['status']}]" for r in rows}))[:110]
        return f"  成交 昨{w['y']} 7d{w['7d']} 30d{w['30d']} 生涯{w['life']:>3}  {nm[:38]!r}\n        └ {loc}"

    print("\n" + "═" * 90)
    print(f" B. 有成交但没在跑的广告  (🔴 广告被单独关 {len(ad_paused)} · "
          f"🟡 系列/组关着 {len(container_off)} · ⚪ 不在SG {len(absent)})")
    print("═" * 90)
    print("\n 🔴 广告被单独关掉 (effective_status=PAUSED) —— 有成交却被关,优先考虑重开:")
    for w, rows in sorted(ad_paused, key=_key):
        print(_line(w, rows))
    if not ad_paused:
        print("   （没有：没有任何‘有成交’的广告是被单独关掉的）")

    print("\n 🟡 系列/广告组关着 (新建未激活 / weekly OFF / 整组暂停) —— 激活容器即可跑:")
    for w, rows in sorted(container_off, key=_key)[:20]:
        print(_line(w, rows))
    if len(container_off) > 20:
        print(f"   … 其余 {len(container_off) - 20} 个略")

    print("\n ⚪ 有成交但 SG 账户里根本没有这支广告 (多半是 MY 专属创意 / 改过名):")
    for w, rows in sorted(absent, key=_key)[:15]:
        print(f"   成交 7d{w['7d']} 30d{w['30d']} 生涯{w['life']:>3}  {w.get('_name','∅')[:46]!r}")
    if len(absent) > 15:
        print(f"   … 其余 {len(absent) - 15} 个略")


if __name__ == "__main__":
    main()
