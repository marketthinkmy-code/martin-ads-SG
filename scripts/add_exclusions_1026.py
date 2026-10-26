"""Add the two exclusion audiences to the Food and Drink + Milk 中英文 ad sets (26 Oct operator: 「加」).

The 中英文 Food and Drink + Milk ad sets were copied from HK ad set 120250334622660335, which
excludes nobody; the Family and Relationships template (HK 120250334621660335) excludes
"15 days complete registration" and "马丁 1997 Paid Student". This copies exactly those
exclusions onto the three fdm:* ad sets in state/entities_lang_1026.json, keeping everything
else in their targeting, then reads each one back. ADBOT_ADSET_IDS overrides the list (26 Oct
operator 「加」 for 孩子挑食); ADBOT_READ_ONLY_IDS only prints exclusions. No other entity is touched.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

FR_TPL = "120250334621660335"


def main():
    log = get_logger()
    g = graph_client(load_settings())
    st = json.loads(Path("state/entities_lang_1026.json").read_text())
    want = (g.get_object(FR_TPL, "targeting").get("targeting") or {}).get("excluded_custom_audiences") or []
    if not want:
        log.error("❌ 模板 %s 读不到排除名单 —— 停止，没有改任何东西。", FR_TPL)
        sys.exit(1)
    log.info("要加的排除名单：%s", [(x.get("id"), x.get("name")) for x in want])
    done = []
    ids = [x.strip() for x in (os.environ.get("ADBOT_ADSET_IDS") or "").split(",") if x.strip()]
    targets = [(f"id:{i}", i) for i in ids] or [(k, v) for k, v in st["adsets"].items() if k.startswith("fdm:")]
    for slot, sid in targets:
        t = g.get_object(sid, "targeting").get("targeting") or {}
        have = {x.get("id") for x in t.get("excluded_custom_audiences") or []}
        t["excluded_custom_audiences"] = [{"id": x["id"]} for x in (t.get("excluded_custom_audiences") or [])] + \
                                         [{"id": x["id"]} for x in want if x["id"] not in have]
        g._request("POST", sid, data={"targeting": json.dumps(t, ensure_ascii=False)})
        back = g.get_object(sid, "name,effective_status,targeting{excluded_custom_audiences,locales}").get("targeting") or {}
        log.info("  ad set %s (%s) · 排除 %s · 语言 %s", sid, slot,
                 [x.get("name") or x.get("id") for x in back.get("excluded_custom_audiences") or []], back.get("locales"))
        done.append(sid)
    for sid in [x.strip() for x in (os.environ.get("ADBOT_READ_ONLY_IDS") or "").split(",") if x.strip()]:
        back = g.get_object(sid, "name,effective_status,targeting{excluded_custom_audiences}")
        log.info("  只读 ad set %s %r · %s · 排除 %s", sid, back.get("name"), back.get("effective_status"),
                 [x.get("name") or x.get("id") for x in (back.get("targeting") or {}).get("excluded_custom_audiences") or []] or "没有")
    final_summary(log, f"exclusions added to {len(done)} ad sets: {done}")


if __name__ == "__main__":
    main()
