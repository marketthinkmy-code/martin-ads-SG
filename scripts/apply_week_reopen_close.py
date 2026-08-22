"""Apply the week audit's verdicts: reopen 5 wrongly-killed sellers, close 2 proven losers (6 ads).

Operator-approved 22 Aug, from week_reopen_close_audit.py:

  REOPEN — switched off on registration cost, but the creative has provably-SG sales at a CPA
  inside the acceptable line. Registration cost alone never kills a money-making ad:
      牛奶+面包 (Winners Revival) · DEC HOOK 13 (H&W) · Video 12 試了五六種 (Interest: Family)
      · Carousel 别再逼孩子喝牛奶了 (迷思打破 B) · Single Image 女孩来了初经 (单图-迷思)

  CLOSE — still running with a proven, well-funded CPA above the RM1,300 hard stop:
      MAR Video 8（1） in H&W (CPA 1,517 on RM15k) · MAR Video 1 我不会买牛奶 in all five
      LAL 1-5-3 bands (CPA 2,231 on RM27k). Each band keeps 15岁以上 running.

MATCHING, DELIBERATELY PARANOID
-------------------------------
Ads are found by name-key containment INSIDE a specific campaign (key containment again), and
every target declares how many ads it expects to match. The check phase runs over ALL targets
first; one wrong count anywhere aborts the whole run before anything is touched — the same
creative name exists in other campaigns (copies, "- Copy" variants, a halfwidth-colon twin of
我不会买牛奶 in Scale-Winners) and none of those may be caught.

Idempotent: targets already in the desired state are counted as done, so a re-run changes
nothing. Every write is verified by re-reading the stored status.
"""
from __future__ import annotations

from typing import Any, Dict, List

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

# action · name-key fragment · campaign-key fragment · how many ads this MUST match
TARGETS: List[Dict[str, Any]] = [
    {"act": "reopen", "name": "MAR Single image 1：牛奶+面包", "camp": "Winners Revival", "n": 1},
    {"act": "reopen", "name": "DEC HOOK 13：花了几千块买增高 supplement", "camp": "Health & Wellness", "n": 1},
    {"act": "reopen", "name": "Video 12：15歲以上試了五六種方法沒長高", "camp": "Interest: Family", "n": 1},
    {"act": "reopen", "name": "Carousel：别再逼孩子喝牛奶了", "camp": "迷思打破", "n": 1},
    {"act": "reopen", "name": "Single Image：女孩来了初经", "camp": "单图-迷思", "n": 1},
    {"act": "close", "name": "MAR Video 8（1）：新马版主打牛奶迷思", "camp": "Health & Wellness", "n": 1},
    {"act": "close", "name": "MAR Video 1：我不会买牛奶", "camp": "PURCHASE LAL 1-5%", "n": 5},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    ads = g._get_all(f"{s.meta.account_path}/ads", {
        "fields": "id,name,status,effective_status,campaign{name}", "limit": 500})

    # ── check phase: resolve every target before touching anything ──────────────
    plans: List[Dict[str, Any]] = []
    problems: List[str] = []
    for t in TARGETS:
        nk, ck = cpa.ad_key(t["name"]), cpa.ad_key(t["camp"])
        hits = [a for a in ads
                if nk in cpa.ad_key(a.get("name", ""))
                and ck in cpa.ad_key((a.get("campaign") or {}).get("name", ""))]
        if len(hits) != t["n"]:
            problems.append(f"{t['name'][:30]} in {t['camp']}: expected {t['n']} ad(s), "
                            f"found {len(hits)} ({[a['id'] for a in hits]})")
            continue
        plans.append({**t, "hits": hits})
    if problems:
        for p in problems:
            log.error("!! %s", p)
        raise SystemExit("!! target resolution failed — NOTHING was changed. The account does "
                         "not look like the audit this plan was approved against.")

    # ── act phase ────────────────────────────────────────────────────────────────
    changed, already, failed = 0, 0, 0
    for p in plans:
        want = "ACTIVE" if p["act"] == "reopen" else "PAUSED"
        for a in p["hits"]:
            label = f"{a['name'][:34]} ({a['id']})"
            if a.get("status") == want:
                already += 1
                log.info("· %-6s %s already %s", p["act"], label, want)
                continue
            g._request("POST", a["id"], data={"status": want})
            chk = g._request("GET", a["id"], params={"fields": "status,effective_status"})
            ok = chk.get("status") == want
            changed += int(ok)
            failed += int(not ok)
            log.info("%s %-6s %s → %s (effective %s)", "✓" if ok else "✗", p["act"], label,
                     chk.get("status"), chk.get("effective_status"))

    log.info("═" * 96)
    final_summary(
        log, f"Applied and verified from stored statuses: {changed} change(s), {already} already "
             f"in the desired state, {failed} FAILED. Reopened the 5 wrongly-killed sellers "
             f"(牛奶+面包 · DEC HOOK 13 · Video 12 · 别再逼孩子喝牛奶 · 女孩来了初经) and closed "
             f"the 2 proven losers (Video 8(1) in H&W · 我不会买牛奶 in all 5 LAL bands — each "
             f"band keeps 15岁以上 running). The CPL guardrail may try to re-pause the reopened "
             f"ads next run if their weekly CPL stays over the ceiling; if that happens, add "
             f"their names to kpi.cpl_hold in config.")


if __name__ == "__main__":
    main()
