"""Find each Top-15 (by paid sales) ad NAME inside the SG ad account and report
its reusable creative_id (video_id / image_hash is account-scoped; creative_id is
directly reusable to create new ads in the SAME account).

Robust matching: normalises traditional→simplified + full-width punctuation +
strips spaces, matches EXACT first, and for anything that is not an exact hit,
dumps up to 6 candidate SG ad names (with creative_id) so the mapping can be
locked by eye. Read-only.
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

# just the traditional chars that appear across these winner names / their SG variants
TRAD2SIMP = str.maketrans({
    "麵": "面", "書": "书", "長": "长", "見": "见", "證": "证", "馬": "马",
    "頭": "头", "個": "个", "會": "会", "還": "还", "學": "学", "習": "习",
    "歲": "岁", "對": "对", "來": "来", "媽": "妈", "屬": "属", "營": "营",
    "養": "养", "師": "师", "後": "后", "們": "们", "屆": "届",
})
PUNCT = str.maketrans({
    "：": ":", "（": "(", "）": ")", "～": "~", "！": "!", "？": "?",
    "，": ",", "．": ".", "－": "-", "—": "-", "–": "-", "、": ",",
})


def norm(s: str) -> str:
    s = (s or "").strip().lower().translate(TRAD2SIMP).translate(PUNCT)
    return re.sub(r"\s+", "", s)


def longest_cjk(s: str) -> str:
    runs = re.findall(r"[一-鿿]+", s.translate(TRAD2SIMP))
    return max(runs, key=len) if runs else ""


def _cid(a: dict):
    return (a.get("creative") or {}).get("id")


def main() -> None:
    s = load_settings()
    g = GraphClient(s.secrets.meta_token, "")

    ads = g._get_all(f"{SG_ACCT}/ads",
                     {"fields": "name,effective_status,creative{id}", "limit": 500})
    print(f"SG account {SG_ACCT}: {len(ads)} ads pulled\n")
    idx = [(norm(a.get("name", "")), a) for a in ads]

    exact_hits = 0
    for i, top in enumerate(TOP15, 1):
        nt = norm(top)
        exact = [a for (na, a) in idx if na == nt]
        print(f"#{i:>2}  {top}")
        if exact:
            exact_hits += 1
            best = sorted(exact, key=lambda a: 0 if a.get("effective_status") == "ACTIVE" else 1)[0]
            print(f"      ✓ EXACT ({len(exact)} ad) · creative_id={_cid(best)} · "
                  f"name={best.get('name')!r} ({best.get('effective_status')})")
            continue
        tok = norm(longest_cjk(top))
        cands = [a for (na, a) in idx if tok and tok in na]
        # de-dup candidate NAMES, keep first creative per name
        seen: dict[str, dict] = {}
        for a in cands:
            seen.setdefault(a.get("name", ""), a)
        cand_list = list(seen.items())[:6]
        print(f"      ✗ no exact · fuzzy token={tok!r} · {len(seen)} candidate name(s):")
        for nm, a in cand_list:
            print(f"          • creative_id={_cid(a)} · {nm!r} ({a.get('effective_status')})")
        print()

    print(f"═══ {exact_hits}/15 exact; resolve the rest from candidates above ═══")


if __name__ == "__main__":
    main()
