"""Build the SG-only "Cust Paid List" seed audience + its 1%-5% lookalike.

Supersedes the first attempt, which seeded on all markets. The operator audited the row-level
export (scripts/export_paid_list_audit.py, which shares this script's extraction via
adbot.paid_list so the audited list and the uploaded list cannot drift) and chose SG only.

WHAT SEEDS IT
-------------
adbot.paid_list.extract() with option-B exclusions (both Refund tabs + VIP upgrade RM88), then
filtered to country == "SG". Country comes from the phone's dialling code; a row with no phone
is "unknown" and is NOT treated as SG, so the seed is genuinely Singapore-only rather than
Singapore-plus-whatever-had-no-phone.

That was 448 rows at the time of the audit. It is above Meta's 100-matched-person floor but
below the 1,000-5,000 it wants, so the lookalike will be workable but coarser than an
all-markets seed would have been. That trade is the operator's, made with the numbers in hand.

THE SEED MUST BE FRESH, NOT TOPPED UP
-------------------------------------
A customer-list upload is an UPSERT: it adds people, it never replaces them. So the SG rows
cannot simply be uploaded onto the previous all-markets audience — that would leave the 1,998
international rows sitting in it and produce a superset, not an SG list. The previous seed
(120257734475910093) and its lookalike (120257734521500093) were therefore deleted before this
runs, and state was cleared so a brand-new audience is created here.

For the same reason a re-dispatch of THIS script is safe only while the filter is unchanged:
re-running refreshes the same SG audience with new SG buyers. If the filter ever changes again,
delete the audience first — topping up cannot narrow a list.

PII HANDLING
------------
Emails and phones are normalised and SHA-256 hashed ON THIS RUNNER before any network call, so
only digests leave the process. Nothing raw is logged, written to state/, or committed — this
repo is public and the logs carry counts only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from adbot import paid_list
from adbot.clients.drive import build_credentials
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_lookalike_paid.json"
SEED_NAME = "Cust Paid List (SG)"
TARGET_COUNTRY = "SG"
SEED_COUNTRIES = {"SG"}                  # the operator's choice: Singapore buyers only
# A bare 8-digit number beginning 8/9 is treated as +65. That is right for most rows but a Hong
# Kong mobile is also 8 digits (beginning 5/6/9), so some "SG" rows are inferred rather than
# confirmed. Default False = keep them, because dropping them shrinks an already-small seed;
# flip to True if the audit shows the inferred rows are actually foreign.
SEED_REQUIRE_EXPLICIT_CC = False
# (starting_ratio, ratio) — a pair is a RANGE audience, what Meta calls "1% to 5%".
LOOKALIKES = [(0.01, 0.05)]
BATCH = 500                              # rows per upload call; Meta allows 10k, 500 keeps errors legible
MIN_SEED = 100                           # Meta's hard floor for matched people


def sha256(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    sid = s.cpa.spreadsheet_id
    if not sid:
        raise SystemExit("!! cpa.spreadsheet_id is not configured")

    from googleapiclient.discovery import build  # lazy
    sheets = build("sheets", "v4", credentials=build_credentials(s.secrets.google_sa_json),
                   cache_discovery=False)

    all_rows, kept, excluded = paid_list.extract(sheets, sid, log)
    tally = paid_list.tally(all_rows)
    rows = [r for r in all_rows if r.country in SEED_COUNTRIES]

    log.info("═" * 88)
    log.info("%d paid tab(s) kept, %d excluded → %d unique row(s) before the country filter",
             kept, excluded, len(all_rows))
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        log.info("   %-8s %5d%s", k, v, "  ← seeding on this" if k in SEED_COUNTRIES else "")
    inferred = sum(1 for r in rows if r.cc == "inferred")
    log.info("seed = %s only → %d row(s)  (%d explicit +65, %d inferred from a bare 8-digit number)",
             "/".join(sorted(SEED_COUNTRIES)), len(rows), len(rows) - inferred, inferred)
    if inferred:
        log.warning("   ⚠ %d row(s) are INFERRED SG — a Hong Kong mobile typed without +852 is "
                    "8 digits beginning 5/6/9 and cannot be told apart from a Singapore one. "
                    "They are INCLUDED; set SEED_REQUIRE_EXPLICIT_CC to drop them.", inferred)
        if SEED_REQUIRE_EXPLICIT_CC:
            rows = [r for r in rows if r.cc == "explicit"]
            log.info("   → dropped inferred rows, seeding on %d confirmed row(s)", len(rows))

    if len(rows) < MIN_SEED:
        raise SystemExit(f"!! only {len(rows)} {'/'.join(sorted(SEED_COUNTRIES))} contacts — Meta "
                         f"needs >={MIN_SEED} matched people; refusing to build a lookalike that "
                         f"cannot deliver")

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    # 1) seed audience ───────────────────────────────────────────────────────────────
    seed_id = st.get("seed_audience_id")
    if seed_id:
        # Safe only because the filter is unchanged — an upsert can add SG buyers but can never
        # remove non-SG ones. Changing SEED_COUNTRIES requires deleting the audience first.
        log.info("reusing seed audience %s (upsert — refreshes it with any new SG buyers)", seed_id)
    else:
        seed_id = g._request("POST", f"{acct}/customaudiences", data={
            "name": SEED_NAME,
            "subtype": "CUSTOM",
            "customer_file_source": "USER_PROVIDED_ONLY",
            "description": "Singapore paid students (+65), rebuilt from the Paid Student List "
                           "spreadsheet. Excludes refunds and the RM88 VIP upgrade tier.",
        })["id"]
        st = {"seed_audience_id": seed_id, "seed_countries": sorted(SEED_COUNTRIES),
              "lookalikes": {}}
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("+ seed audience %s %r", seed_id, SEED_NAME)

    # 2) upload hashed rows ──────────────────────────────────────────────────────────
    payload: List[List[str]] = [[sha256(r.email) if r.email else "",
                                 sha256(r.phone) if r.phone else ""] for r in rows]
    sent = 0
    for i in range(0, len(payload), BATCH):
        chunk = payload[i:i + BATCH]
        g._request("POST", f"{seed_id}/users", data={"payload": json.dumps(
            {"schema": ["EMAIL", "PHONE"], "data": chunk})})
        sent += len(chunk)
        log.info("   ↑ uploaded %d/%d hashed row(s)", sent, len(payload))

    # 3) lookalike ───────────────────────────────────────────────────────────────────
    lals: Dict[str, str] = st.get("lookalikes", {})
    made = []
    for start, ratio in LOOKALIKES:
        key = f"{ratio:.2f}" if start is None else f"{start:.2f}-{ratio:.2f}"
        band = f"{int(ratio*100)}%" if start is None else f"{int(start*100)}% to {int(ratio*100)}%"
        if lals.get(key):
            log.info("   · lookalike %s already exists (%s)", band, lals[key])
            continue
        name = f"Lookalike ({TARGET_COUNTRY}, {band}) - {SEED_NAME}"
        spec: Dict[str, Any] = {"ratio": ratio, "country": TARGET_COUNTRY}
        if start is not None:
            spec["starting_ratio"] = start
        try:
            lal_id = g._request("POST", f"{acct}/customaudiences", data={
                "name": name, "subtype": "LOOKALIKE", "origin_audience_id": seed_id,
                "lookalike_spec": json.dumps(spec)})["id"]
        except Exception as exc:                                   # noqa: BLE001
            # Expected on a first run if the seed has not finished matching. Not fatal — the seed
            # is the expensive part and is kept; a re-dispatch adds the lookalike.
            log.warning("   !! lookalike %s failed (seed may still be matching): %s", band, exc)
            continue
        lals[key] = lal_id
        st["lookalikes"] = lals
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        made.append(f"{band}={lal_id}")
        log.info("   + lookalike %s → %s", name, lal_id)

    log.info("═" * 88)
    final_summary(
        log, f"{SEED_NAME} ({seed_id}) built from {len(rows)} Singapore paid contacts — option-B "
             f"exclusions applied ({excluded} tab(s): both refund tabs + VIP upgrade RM88) and "
             f"filtered to +65 only, with no-phone rows left out rather than assumed SG. "
             f"Lookalike: {', '.join(made) if made else 'none created this run'}. Meta takes a few "
             f"hours to match the list and size the lookalike; it cannot be used until then. "
             f"Emails and phones were SHA-256 hashed on this runner — nothing raw was logged or "
             f"stored. No ad set was touched; nothing targets this until you attach it by hand.")


if __name__ == "__main__":
    main()
