"""Apply operator-approved campaign changes (budgets + closes) — LIVE writes.

Approved 2026-07-24:
  ⬆️ Scale-CBO 2            RM250 → RM300
  ⬆️ Parents 3–17 | 1-1-3   RM100 → RM130   (the ACTIVE one, not the paused dup)
  ⬆️ Family | 1-1-3 (RM250) RM250 → RM300
  🔴 Scale-CBO (original)    ACTIVE → PAUSED (over-CPL, weak recent paid conversion)
  🔴 Family | 1-1-3 (RM100)  ACTIVE → PAUSED (broken duplicate — 1 reg / CPL 286)

Each target is matched by name tokens + EXACT current daily_budget (cents) + ACTIVE status,
so the correct campaign of a duplicate-named pair is selected. If a target is missing, already
at goal, or AMBIGUOUS (≠1 match), it is SKIPPED and logged — never guessed. Re-running is a
no-op (post-change budget/status no longer matches). Reads then writes; prints an audit trail.
"""
from __future__ import annotations

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


# each: label · name must contain ALL these tokens · must NOT contain any exclude token ·
#       exact current budget (cents) · then either set_budget (cents) or set_status
ACTIONS = [
    {"label": "Scale-CBO 2 → RM300",          "has": ["scale-cbo 2"],                          "not": [],             "budget": 25000, "set_budget": 30000},
    {"label": "Parents 3–17 1-1-3 → RM130",    "has": ["parents 3", "1-1-3"],                   "not": [],             "budget": 10000, "set_budget": 13000},
    {"label": "Family 1-1-3 (RM250) → RM300",  "has": ["family and relationships", "1-1-3"],    "not": [],             "budget": 25000, "set_budget": 30000},
    {"label": "Scale-CBO (original) → PAUSED", "has": ["scale-cbo"],                            "not": ["scale-cbo 2"], "budget": 20000, "set_status": "PAUSED"},
    {"label": "Family 1-1-3 (RM100 dup) → PAUSED", "has": ["family and relationships", "1-1-3"], "not": [],            "budget": 10000, "set_status": "PAUSED"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    camps = g._get_all(f"{acct}/campaigns",
                       {"fields": "id,name,effective_status,daily_budget", "limit": 300})

    def cents(c) -> int:
        try:
            return int(c.get("daily_budget") or 0)
        except (TypeError, ValueError):
            return 0

    log.info("account has %d campaigns; ACTIVE with a CBO budget:", len(camps))
    for c in sorted((c for c in camps if c.get("effective_status") == "ACTIVE" and cents(c)),
                    key=lambda c: -cents(c)):
        log.info("   [%s] RM%-4.0f  %s", c["id"], cents(c) / 100, c.get("name"))
    log.info("─" * 90)

    summary = []
    for a in ACTIONS:
        m = [c for c in camps
             if all(t in _norm(c.get("name")) for t in a["has"])
             and not any(x in _norm(c.get("name")) for x in a["not"])
             and c.get("effective_status") == "ACTIVE"
             and cents(c) == a["budget"]]
        if len(m) != 1:
            log.error("⏭ SKIP %s — found %d matches (need exactly 1)", a["label"], len(m))
            for cc in m:
                log.error("       candidate [%s] RM%.0f '%s'", cc["id"], cents(cc) / 100, cc.get("name"))
            summary.append(f"  ⏭ SKIP {a['label']} ({len(m)} matches — not applied)")
            continue
        c = m[0]
        cid, nm = c["id"], c.get("name")
        if "set_budget" in a:
            g._request("POST", cid, data={"daily_budget": str(a["set_budget"])})
            log.info("✔ %s  [%s]", a["label"], cid)
            summary.append(f"  ⬆️ RM{a['budget']/100:.0f}→RM{a['set_budget']/100:.0f}  {nm}  [{cid}]")
        else:
            g.update_status(cid, a["set_status"])
            log.info("✔ %s  [%s]", a["label"], cid)
            summary.append(f"  🔴 → {a['set_status']}  {nm}  [{cid}]")

    log.info("═" * 90)
    for line in summary:
        log.info(line)
    final_summary(log, "Applied approved campaign changes (budgets + closes). See audit trail above.")


if __name__ == "__main__":
    main()
