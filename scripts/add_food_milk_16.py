"""Fill Food & Drink + Milk's 3rd ad slot with the next-ranked (#16+) paid-sales
winner that (a) exists in the SG account and (b) isn't one of the 14 already
placed. Reuses the winner's SG creative_id; creates ONE PAUSED ad in the
Food&Milk ad set and appends it to state.

Idempotent: if the Food&Milk state already lists 3 ads, this is a no-op.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

FOOD_MILK_ADSET = "120256415719440093"
STATE = Path("state/entities_audtest_food_drink_milk.json")

# the 14 Top-15 winners already placed across the 5 ad sets (skip so we don't dup)
USED_CREATIVES = {
    "916687424478259", "2497538107356049", "1935626953763958", "1669165664097834",
    "1820162411994952", "869719622756516", "1851193622390034", "4385226148411505",
    "1768067630797625", "27996687696586337", "2027354148165419", "1422998433168117",
    "1535988271344314", "838714645189319",
}

TRAD2SIMP = str.maketrans({
    "麵": "面", "書": "书", "長": "长", "見": "见", "證": "证", "馬": "马",
    "頭": "头", "個": "个", "會": "会", "還": "还", "學": "学", "習": "习",
    "歲": "岁", "對": "对", "來": "来", "媽": "妈", "師": "师", "後": "后", "們": "们",
})
PUNCT = str.maketrans({
    "：": ":", "（": "(", "）": ")", "～": "~", "！": "!", "？": "?",
    "，": ",", "．": ".", "－": "-", "—": "-", "–": "-", "、": ",",
})


def norm(s: str) -> str:
    s = (s or "").strip().lower().translate(TRAD2SIMP).translate(PUNCT)
    return re.sub(r"\s+", "", s)


def main() -> None:
    log = get_logger()
    s = load_settings()

    st = json.loads(STATE.read_text())
    if len(st.get("ad_ids", [])) >= 3:
        log.info("Food&Milk already has %d ads — nothing to do", len(st["ad_ids"]))
        return

    g = graph_client(s)

    # 1) reproduce the whole-sheet ad ranking (same logic as all_top15_ads.py)
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    name_sales: dict[str, int] = defaultdict(int)
    for sale in sales:
        if sale.ad:
            name_sales[sale.ad] += 1
    ranked = sorted(name_sales.items(), key=lambda kv: -kv[1])

    # 2) SG account ads -> creative id, matched by normalised name
    ads = g._get_all(f"{s.meta.account_path}/ads",
                     {"fields": "name,creative{id}", "limit": 500})
    idx = [(norm(a.get("name", "")), a) for a in ads]

    # 3) walk ranks 16.. and pick the first winner present in SG w/ an unused creative
    print("Next-rank candidates (rank · sales · SG creative_id · name):")
    chosen = None
    for rank in range(16, 31):
        if rank - 1 >= len(ranked):
            break
        name, cnt = ranked[rank - 1]
        nt = norm(name)
        cid = None
        for na, a in idx:
            if na == nt:
                c = (a.get("creative") or {}).get("id")
                if c and c not in USED_CREATIVES:
                    cid = c
                    break
        mark = ""
        if cid and not chosen:
            chosen = (rank, name, cnt, cid)
            mark = "  ← PICK"
        print(f"  #{rank:>2} · {cnt:>3} sales · creative={cid} · {name!r}{mark}")

    if not chosen:
        log.error("no usable next-rank winner found in the SG account (ranks 16-30)")
        return

    rank, name, cnt, cid = chosen
    ad = g.create_ad(s.meta.account_path, name=name, adset_id=FOOD_MILK_ADSET,
                     creative={"creative_id": cid}, status="PAUSED",
                     conversion_domain=s.meta.conversion_domain_bare or None)
    log.info("created ad %s ⟵ creative %s  (#%d %s · %d sales)",
             ad["id"], cid, rank, name, cnt)

    st["ad_ids"].append(ad["id"])
    st.setdefault("built_content_ids", []).append(name)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    final_summary(log, f"Food&Milk 3rd ad added: #{rank} {name!r} ({cnt} sales) "
                       f"→ ad {ad['id']} (PAUSED). Ad set now 3/3.")


if __name__ == "__main__":
    main()
