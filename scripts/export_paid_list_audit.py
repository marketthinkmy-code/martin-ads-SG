"""Export the Cust Paid List seed to a Google Sheet for the operator to audit. Touches NO Meta.

This is a READ-ONLY audit step. It does not create, update or delete a single Meta object — the
operator asked to review the row-level list before it is uploaded again, so this only produces
the evidence.

WHAT CHANGED VS THE FIRST UPLOAD (option B)
-------------------------------------------
The first run's tab-level audit surfaced two problems, and both are fixed by EXCLUDED_GIDS:

  · Refund (gid 1847972349, 19 rows) and US Refund (gid 254146896, 15 rows) are people who
    bought and then took their money back. They were swept in because their headers carry an
    "Amount" column, which is one of the PAID markers. Modelling a lookalike on refunders asks
    Meta to go find more people who will refund — the exact opposite of the goal.
  · VIP upgrade (RM88) (gid 697093187, 512 rows) is a different customer from an RM1997 or
    RM18k buyer, and at 26% of the seed it was diluting the high-value signal.

WHY A COUNTRY COLUMN
--------------------
The operator wants to confirm the list is SG only. Country is derived from the phone's country
code, which is the same rule the CPA layer uses to isolate SG sales (+65). A row whose phone is
missing cannot be placed in a country at all — those land in "unknown" rather than being quietly
counted as SG, because guessing there would be the one error that makes an "SG only" audit
worthless.

Note the earlier "SG has only ~197" figure was computed from a TRUNCATED Drive text export and
should not be trusted; this script counts from the live Sheets API, which is where the real
number comes from.

OUTPUT
------
Creates a new spreadsheet owned by the service account and shares it with AUDIT_SHARE_TO, with
two tabs so the operator can compare before deciding:
    "SG only"      — rows whose phone is +65
    "All markets"  — every row that survived the exclusions, with its country
Raw contact details are written ONLY into that sheet, which lives in the operator's own Google
account. Nothing raw is logged here, written to state/, or committed — the repo is public.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

from adbot.clients.drive import build_credentials
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

# A workflow_dispatch input arrives as "" when left blank, and "" would silently share the
# workbook with nobody — so fall back on the default rather than trusting the empty string.
AUDIT_SHARE_TO = (os.environ.get("ADBOT_AUDIT_EMAIL") or "").strip() or "marketthinkchatgpt@gmail.com"
SHEET_TITLE = os.environ.get("ADBOT_AUDIT_TITLE", "Cust Paid List — 审核")

# Option B: drop refunders and the RM88 upgrade tier.
EXCLUDED_GIDS: Dict[int, str] = {
    1847972349: "Refund — bought then refunded",
    254146896:  "US Refund — bought then refunded",
    697093187:  "VIP upgrade (RM88) — different tier, was 26% of the seed",
}

PAID_HEADER = re.compile(r"(Item purchase|Purchase amount|付費管道|Transaction Id|Amount)", re.I)
EMAIL_COL = re.compile(r"mail", re.I)
PHONE_COL = re.compile(r"phone|whatsapp|號碼|号码", re.I)
NAME_COL = re.compile(r"^\s*(name|名字|姓名)\s*$", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def norm_email(v: str) -> str:
    v = (v or "").strip().lower().replace("\\", "")
    return v if EMAIL_RE.match(v) else ""


def norm_phone(v: str) -> str:
    d = re.sub(r"\D", "", (v or "").replace("\\", ""))
    if not d:
        return ""
    if len(d) == 8 and d[0] in "89":          # bare SG mobile written without +65
        d = "65" + d
    return d if 8 <= len(d) <= 15 else ""


def country_of(phone: str) -> str:
    """Country from the dialling code. No phone -> 'unknown', never a guess."""
    if not phone:
        return "unknown"
    if phone.startswith("65") and len(phone) == 10:
        return "SG"
    if phone.startswith("60"):
        return "MY"
    if phone.startswith("852"):
        return "HK"
    if phone.startswith("886"):
        return "TW"
    if phone.startswith("1") and len(phone) == 11:
        return "US/CA"
    if phone.startswith("86"):
        return "CN"
    if phone.startswith("62"):
        return "ID"
    if phone.startswith("66"):
        return "TH"
    if phone.startswith("44"):
        return "UK"
    if phone.startswith("61"):
        return "AU"
    return "other"


def main() -> None:
    log = get_logger()
    s = load_settings()
    sid = s.cpa.spreadsheet_id
    if not sid:
        raise SystemExit("!! cpa.spreadsheet_id is not configured")

    from googleapiclient.discovery import build  # lazy
    creds = build_credentials(s.secrets.google_sa_json)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    meta = sheets.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties").execute()
    tabs = [(p["properties"]["title"], int(p["properties"]["sheetId"])) for p in meta["sheets"]]
    log.info("spreadsheet has %d tab(s)", len(tabs))

    seen: set[Tuple[str, str]] = set()
    rows: List[List[str]] = []
    paid_tabs = excluded_tabs = 0
    for title, gid in tabs:
        try:
            values = (sheets.spreadsheets().values()
                      .get(spreadsheetId=sid, range=f"'{title}'",
                           valueRenderOption="FORMATTED_VALUE",
                           dateTimeRenderOption="FORMATTED_STRING").execute()).get("values", [])
        except Exception as exc:                                   # noqa: BLE001
            log.warning("   ! could not read %r (gid %s): %s", title, gid, exc)
            continue
        if not values:
            continue
        hdr_i = next((i for i, r in enumerate(values[:10])
                      if any(EMAIL_COL.search(c or "") for c in r)
                      and any(PHONE_COL.search(c or "") for c in r)), None)
        if hdr_i is None:
            continue
        hdr = values[hdr_i]
        if not PAID_HEADER.search(" | ".join(hdr)):
            continue
        if gid in EXCLUDED_GIDS:
            excluded_tabs += 1
            log.info("   ⛔ %-40s gid=%-12s EXCLUDED — %s", title[:40], gid, EXCLUDED_GIDS[gid])
            continue
        ei = next((k for k, c in enumerate(hdr) if EMAIL_COL.search(c or "")), None)
        pi = next((k for k, c in enumerate(hdr) if PHONE_COL.search(c or "")), None)
        ni = next((k for k, c in enumerate(hdr) if NAME_COL.match(c or "")), None)
        before = len(rows)
        for r in values[hdr_i + 1:]:
            em = norm_email(r[ei]) if ei is not None and ei < len(r) else ""
            ph = norm_phone(r[pi]) if pi is not None and pi < len(r) else ""
            if not (em or ph) or (em, ph) in seen:
                continue
            seen.add((em, ph))
            nm = (r[ni].strip() if ni is not None and ni < len(r) else "")
            rows.append([title, nm, em, ph, country_of(ph)])
        paid_tabs += 1
        log.info("   ✔ %-40s gid=%-12s +%d row(s)", title[:40], gid, len(rows) - before)

    if not rows:
        raise SystemExit("!! nothing to audit — refusing to create an empty sheet")

    counts: Dict[str, int] = {}
    for r in rows:
        counts[r[4]] = counts.get(r[4], 0) + 1
    sg = [r for r in rows if r[4] == "SG"]

    log.info("═" * 88)
    log.info("%d paid tab(s) kept, %d excluded → %d unique row(s)", paid_tabs, excluded_tabs, len(rows))
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        log.info("   %-8s %5d", k, v)
    log.info("SG-only rows: %d", len(sg))
    if len(sg) < 100:
        log.warning("!! SG-only is %d, under Meta's 100-matched-person floor — an SG-only seed "
                    "would not be able to build a lookalike", len(sg))

    # ── write the audit workbook ─────────────────────────────────────────────────────
    head = ["Source Tab", "Name", "Email", "Phone (normalised)", "Country"]
    book = sheets.spreadsheets().create(body={
        "properties": {"title": SHEET_TITLE},
        "sheets": [{"properties": {"title": "SG only"}}, {"properties": {"title": "All markets"}}],
    }, fields="spreadsheetId,spreadsheetUrl").execute()
    bid, url = book["spreadsheetId"], book["spreadsheetUrl"]
    sheets.spreadsheets().values().batchUpdate(spreadsheetId=bid, body={
        "valueInputOption": "RAW",
        "data": [
            # Phones are text, not numbers — RAW would otherwise strip a leading digit visually.
            {"range": "'SG only'!A1",     "values": [head] + [[c for c in r] for r in sg]},
            {"range": "'All markets'!A1", "values": [head] + [[c for c in r] for r in rows]},
        ]}).execute()

    try:
        drive.permissions().create(
            fileId=bid, sendNotificationEmail=False,
            body={"type": "user", "role": "writer", "emailAddress": AUDIT_SHARE_TO}).execute()
        shared = f"shared with {AUDIT_SHARE_TO}"
    except Exception as exc:                                       # noqa: BLE001
        shared = f"‼ could not share with {AUDIT_SHARE_TO}: {exc} — open it with the link"
    log.info("audit workbook: %s (%s)", url, shared)

    final_summary(
        log, f"AUDIT ONLY — no Meta object was created, updated or deleted. Option B applied: "
             f"{excluded_tabs} tab(s) excluded (both refund tabs + VIP upgrade RM88), leaving "
             f"{len(rows)} unique rows across {paid_tabs} paid tab(s), of which {len(sg)} are SG "
             f"(+65). Country comes from the dialling code; rows with no phone are 'unknown', not "
             f"assumed SG. Review here: {url} ({shared}). Tabs: 'SG only' and 'All markets'.")


if __name__ == "__main__":
    main()
