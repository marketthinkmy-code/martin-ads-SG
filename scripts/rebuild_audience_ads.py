"""Swap the 5 audience-test ad sets' creatives to the Top-15 (by paid sales)
WINNERS, in place.

The 5 campaigns / ad sets (targeting, CBO RM100/day, schedule) are correct and
stay untouched — only the 3 ads inside each ad set are replaced: the placeholder
成绩 social-proof ads are deleted and 3 new ads are created that REUSE each
winner's existing SG-account creative_id (video + copy verbatim, so future UTM
attribution keeps matching the winner name).

Distribution = Top-15 in rank order, 3 per audience:
  Parents ← #1-3 · Family ← #4-6 · Housewife ← #7-9 · Food&Milk ← #10-11 · Education ← #13-15
#12 'JAN Video 10: 马六甲' is NOT in the SG account (MY-only), so Food&Milk gets 2 ads.

Idempotent per ad set: only rebuilds an ad set whose recorded ad_ids still point
at the old placeholder ads; state is rewritten with the new ad_ids so a re-run
is a no-op.
"""
from __future__ import annotations

import json
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")

# state_key -> [(ad name = winner utm name, reusable SG creative_id), ...]
PLAN: dict[str, list[tuple[str, str]]] = {
    "entities_audtest_parents_3_17_engaged": [
        ("Video 2 - 一个3～15岁正常健康的孩子", "916687424478259"),
        ("MAR Video 1: 我不会买牛奶", "2497538107356049"),
        ("Video: 孩子15岁以上还有机会长高吗?", "1935626953763958"),
    ],
    "entities_audtest_family_and_relationships": [
        ("JAN Video 6: 如果你的孩子", "1669165664097834"),
        ("MAR Video Hook 3: 准备早餐面包", "1820162411994952"),
        ("Hook 18: 13 141cm", "869719622756516"),
    ],
    "entities_audtest_housewife": [
        ("Extra Video 1 - 鼻子敏感", "1851193622390034"),
        ("MAR Video 5: 林書豪 story", "4385226148411505"),
        ("MAY Video Hook 1: 10 个孩子会有 8 个", "1768067630797625"),
    ],
    "entities_audtest_food_drink_milk": [
        ("Video 8: 麵包牛奶", "27996687696586337"),
        ("Video Hook 2: 运动但是没长高", "2027354148165419"),
        # #12 'JAN Video 10: 马六甲' not present in SG account — slot intentionally left empty
    ],
    "entities_audtest_education_tuition": [
        ("见证 1: 短头发 Eunice Ngu", "1422998433168117"),
        ("MAR Video 8(1): 新马版主打牛奶迷思", "1535988271344314"),
        ("Video 1: 迷思喝牛奶增高", "838714645189319"),
    ],
}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    summary: list[str] = []
    for state_key, winners in PLAN.items():
        path = STATE_DIR / f"{state_key}.json"
        st = json.loads(path.read_text())
        adset_id = st["adset_id"]
        old_ad_ids = list(st.get("ad_ids", []))
        already = st.get("built_content_ids", [])

        if already and all(n in already for n, _ in winners) and "成绩" not in " ".join(already):
            log.info("%s already rebuilt (%s) — skip", state_key, adset_id)
            summary.append(f"  {state_key:44} SKIP (already winners)")
            continue

        # 1) create the winner ads (reuse existing SG creatives verbatim)
        new_ids: list[str] = []
        for name, creative_id in winners:
            ad = g.create_ad(acct, name=name, adset_id=adset_id,
                             creative={"creative_id": creative_id}, status="PAUSED",
                             conversion_domain=conv)
            new_ids.append(ad["id"])
            log.info("  + ad %s  ⟵ creative %s  (%s)", ad["id"], creative_id, name)

        # 2) delete the old placeholder (成绩) ads
        for old in old_ad_ids:
            try:
                g._request("DELETE", old)
                log.info("  - deleted old ad %s", old)
            except Exception as e:                          # noqa: BLE001
                log.warning("  ! delete failed for %s: %s", old, e)

        # 3) persist new state
        st["ad_ids"] = new_ids
        st["built_content_ids"] = [n for n, _ in winners]
        path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        summary.append(f"  {state_key:44} adset={adset_id} new_ads={len(new_ids)} "
                       f"(deleted {len(old_ad_ids)})")

    log.info("═" * 80)
    for line in summary:
        log.info(line)
    final_summary(log, "audience-test ads rebuilt to Top-15 winners (14/15; #12 马六甲 "
                       "MY-only). All PAUSED. Food&Milk has 2 ads pending the 马六甲 decision.")


if __name__ == "__main__":
    main()
