"""Lead Quality Phase 1, step 0: what does the Register tab actually hold? (read-only, 6 Nov)

Prints, for the Register tab only: the header row (every column letter + title), row count, and for
the columns the operator named (G date, H source, J/K/L UTM, P–T survey Q1–Q5, U total score) the
distinct values with counts (top 25, cut to 70 chars), plus fill rates for every column. Columns that
look personal (name / phone / email / whatsapp / ic) are reported by title and fill rate ONLY, never
their values; the number of rows whose personal columns contain "test" is counted, not printed.
No writes.
"""
from __future__ import annotations

import string
from collections import Counter

from adbot.clients.sheets import SheetsClient
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

TAB = "Register"
SHOW = {"G", "H", "J", "K", "L", "P", "Q", "R", "S", "T", "U"}
PERSONAL = ("name", "phone", "email", "mail", "whatsapp", "contact", "ic", "姓名", "电话", "電話", "手机", "邮箱")


def col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = string.ascii_uppercase[r] + s
    return s


def main():
    log = get_logger()
    s = load_settings()
    rows = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, TAB)
    hdr = rows[0] if rows else []
    data = rows[1:]
    log.info("分页 %r：表头 1 行 · 数据 %d 行 · 表头 %d 栏", TAB, len(data), len(hdr))
    width = max([len(hdr)] + [len(r) for r in data[:5000]])
    personal_cols = []
    for i in range(width):
        t = hdr[i] if i < len(hdr) else ""
        filled = sum(1 for r in data if i < len(r) and str(r[i]).strip())
        is_p = any(p in t.casefold() for p in PERSONAL) and col(i) not in SHOW
        if is_p:
            personal_cols.append(i)
        log.info("栏 %s %r · 有值 %d / %d%s", col(i), t, filled, len(data), " · 个人资料栏（不显示内容）" if is_p else "")
    for i in range(width):
        c = col(i)
        if c not in SHOW:
            continue
        vals = Counter(str(r[i]).strip()[:70] if i < len(r) else "" for r in data)
        log.info("═" * 90)
        log.info("栏 %s %r · 不同的值 %d 种 · 前 25：", c, hdr[i] if i < len(hdr) else "", len(vals))
        for v, n in vals.most_common(25):
            log.info("   %5d × %r", n, v)
    tests = [n + 2 for n, r in enumerate(data)
             if any(i < len(r) and "test" in str(r[i]).casefold() for i in personal_cols)]
    log.info("个人资料栏含 'test' 的行：%d 行 · 行号 %s", len(tests), tests[:60])
    final_summary(log, f"Register 数据 {len(data)} 行 · {width} 栏 · 含 test 的行 {len(tests)}")


if __name__ == "__main__":
    main()
