"""Read the operator's new 成交名单 sheet (11 Sep) and attribute buyers to ads. Read-only.

The operator handed a different spreadsheet from the config Paid Student List, pointing at
one tab (gid 1805763216). The Drive text export only carried the sheet's early tabs, so this
reads the exact tab through the Sheets API: resolve the gid to its title, dump the header,
and attribute rows to ads by their UTM columns.

PII discipline: names, phones and emails are NEVER logged — only dates, Source and the UTM
campaign/adset/ad values, which is all attribution needs.

Output:
  · every tab's title (so the operator can name tabs in future asks),
  · the target tab's header + row count,
  · per-UTM-ad buyer counts (all rows, and rows dated in the last 30 days),
  · the provably-SG split (campaign UTM carrying the SG marker), and the specific check the
    operator asked for: did 我不会买牛奶 / 15岁以上-family names produce any of the newest
    buyers, or not.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.drive import build_credentials
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

SPREADSHEET_ID = "1NMtGKVHRYFSsUw3-dacNPYDZABcYKi6VZgMR0u_oZRE"
TARGET_GID = 1805763216


def parse_date(s: str):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def main() -> None:
    log = get_logger()
    s = load_settings()
    from googleapiclient.discovery import build
    svc = build("sheets", "v4", credentials=build_credentials(s.secrets.google_sa_json),
                cache_discovery=False)

    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID,
                                  fields="sheets.properties").execute()
    title = None
    log.info("── tabs in the workbook:")
    for sh in meta.get("sheets", []):
        p = sh["properties"]
        mark = "  ← target" if p.get("sheetId") == TARGET_GID else ""
        log.info("   gid=%-12s %r%s", p.get("sheetId"), p.get("title"), mark)
        if p.get("sheetId") == TARGET_GID:
            title = p.get("title")
    if not title:
        raise SystemExit(f"!! no tab with gid {TARGET_GID} in this workbook.")

    rows = (svc.spreadsheets().values()
            .get(spreadsheetId=SPREADSHEET_ID, range=title,
                 valueRenderOption="FORMATTED_VALUE",
                 dateTimeRenderOption="FORMATTED_STRING")
            .execute().get("values", []))
    if not rows:
        raise SystemExit("!! target tab is empty.")

    header = rows[0]
    log.info("── tab %r: %d rows · header: %s", title, len(rows) - 1, header)

    def col(*names):
        for i, h in enumerate(header):
            k = re.sub(r"\W+", "", (h or "").lower())
            for n in names:
                if re.sub(r"\W+", "", n.lower()) in k:
                    return i
        return None

    c_date = col("created date", "date", "created")
    c_camp = col("utm campaign")
    c_adset = col("utm ads set", "utm adset")
    c_ad = col("utm ads name", "utm ad name", "utm ad")
    c_src = col("source")
    log.info("── columns: date=%s campaign=%s adset=%s ad=%s source=%s",
             c_date, c_camp, c_adset, c_ad, c_src)

    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = today - dt.timedelta(days=30)
    all_by_ad: Counter = Counter()
    d30_by_ad: Counter = Counter()
    d30_rows = []
    sg30 = 0
    for r in rows[1:]:
        def get(i):
            return (r[i] if i is not None and i < len(r) else "") or ""
        camp, ad = get(c_camp), get(c_ad)
        d = parse_date(get(c_date))
        key = ad.strip() or "∅ (no UTM ad)"
        all_by_ad[key] += 1
        if d and d >= d30:
            d30_by_ad[key] += 1
            camp_n = cpa.norm(camp)
            is_sg = ("[sg]" in camp_n) or ("martin-sg" in camp_n) or ("martin sg" in camp_n) \
                or ("长高" in camp) or ("長高" in camp)
            sg30 += 1 if is_sg else 0
            d30_rows.append((d.isoformat(), "SG" if is_sg else "—", camp[:46], get(c_adset)[:24],
                             ad[:44], get(c_src)[:24]))

    log.info("═" * 100)
    log.info("最近 30 天的成交行（date · SG · campaign · adset · ad · source）:")
    for row in sorted(d30_rows, reverse=True):
        log.info("   %s  %-2s  %-46s  %-24s  %-44s  %s", *row)
    log.info("═" * 100)
    log.info("最近 30 天 · 按 UTM 广告名 (%d 行，其中 SG 标记 %d):", sum(d30_by_ad.values()), sg30)
    for name, n in d30_by_ad.most_common(30):
        log.info("   %2d  %s", n, name[:70])
    log.info("═" * 100)
    log.info("全表 · 按 UTM 广告名（前 25）:")
    for name, n in all_by_ad.most_common(25):
        log.info("   %2d  %s", n, name[:70])

    watch = ["我不会买牛奶", "15岁以上", "15歲以上", "什麼樣的孩子", "牛奶+面包", "流鼻涕",
             "Hook 9", "Hook Edit 04", "Hook 2", "Hook 1", "Hook 6", "我13岁", "我也是爸爸",
             "鼻子敏感", "如果你的孩子"]
    log.info("═" * 100)
    log.info("重点名字 30 天成交核对:")
    for w in watch:
        n = sum(v for k, v in d30_by_ad.items() if w in k)
        log.info("   %-24s %d", w, n)

    final_summary(
        log, f"Tab {title!r}: {len(rows) - 1} buyer rows; last-30d {sum(d30_by_ad.values())} "
             f"({sg30} SG-marked). Per-ad attributions above; no personal data logged.")


if __name__ == "__main__":
    main()
