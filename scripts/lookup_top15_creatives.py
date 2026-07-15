"""Find each Top-15 (by paid sales) ad NAME inside the SG ad account and pull the
creative behind it (video_id / image_hash + caption + headline).

Why: video_id / image_hash are ACCOUNT-SCOPED, so to rebuild the 5 audience-test
ad sets with the WINNING creatives we need the SG-account copy of each winner.
The SG account is a full clone (770 ad sets), so the winners are very likely
already uploaded there. Read-only — just reports what matched and its reusable
creative id, so build_audience_tests.py can be re-pointed at these.
"""
from __future__ import annotations

import re

from adbot.clients.graph import GraphClient
from adbot.settings import load_settings

SG_ACCT = "act_1024930575770087"

TOP15 = [
    "Video 2 - 一个3～15岁正常健康的孩子",
    "MAR Video 1: 我不会买牛奶",
    "Video: 孩子15岁以上还有机会长高吗?",
    "JAN Video 6: 如果你的孩子",
    "MAR Video Hook 3: 准备早餐面包",
    "Hook 18: 13 141cm",
    "Extra Video 1 - 鼻子敏感",
    "MAR Video 5: 林書豪 story",
    "MAY Video Hook 1: 10 个孩子会有 8 个",
    "Video 8: 麵包牛奶",
    "Video Hook 2: 运动但是没长高",
    "JAN Video 10: 马六甲",
    "见证 1: 短头发 Eunice Ngu",
    "MAR Video 8(1): 新马版主打牛奶迷思",
    "Video 1: 迷思喝牛奶增高",
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def core(name: str) -> str:
    """Drop a leading 'MAR Video 1:' / 'JAN Video 6:' / 'Hook 18:' style prefix."""
    n = re.sub(r"^[A-Za-z0-9 ()#_\-]+[:：\-]\s*", "", name)
    return norm(n)


def main() -> None:
    s = load_settings()
    g = GraphClient(s.secrets.meta_token, "")

    ads = g._get_all(f"{SG_ACCT}/ads",
                     {"fields": "name,effective_status,creative{id}", "limit": 500})
    print(f"SG account {SG_ACCT}: {len(ads)} ads pulled\n")
    idx = [(norm(a.get("name", "")), a) for a in ads]

    found = 0
    for i, top in enumerate(TOP15, 1):
        nt = norm(top)
        ct = core(top)
        hits = [a for (na, a) in idx
                if na == nt or (len(ct) > 5 and ct in na) or (len(na) > 6 and na in nt)]
        print(f"#{i:>2}  {top}")
        if not hits:
            print("      ✗ NO SG-account ad matched this name\n")
            continue
        found += 1
        # resolve the creative of the first match; prefer an ACTIVE-ish one
        best = sorted(hits, key=lambda a: 0 if a.get("effective_status") == "ACTIVE" else 1)[0]
        cid = (best.get("creative") or {}).get("id")
        spec = {}
        try:
            spec = g.get_object(cid, "object_story_spec,video_id,image_hash") if cid else {}
        except Exception as e:                              # noqa: BLE001
            print(f"      ! creative fetch failed for {cid}: {e}")
        oss = spec.get("object_story_spec") or {}
        vd = oss.get("video_data") or {}
        ld = oss.get("link_data") or {}
        vid = vd.get("video_id") or spec.get("video_id")
        img = ld.get("image_hash") or spec.get("image_hash")
        kind = "VIDEO" if vid else ("IMAGE" if img else "?")
        title = vd.get("title") or ld.get("name") or ""
        print(f"      ✓ {len(hits)} SG ad(s) · kind={kind} · video_id={vid} · image_hash={img}")
        print(f"        matched SG name={best.get('name')!r} ({best.get('effective_status')})")
        print(f"        creative_id={cid} · headline={title[:50]!r}\n")

    print(f"═══ {found}/15 Top ads found in the SG account ═══")


if __name__ == "__main__":
    main()
