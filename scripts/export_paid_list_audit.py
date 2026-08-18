"""Export the paid list to "AUDIT ·" tabs in the source workbook. Touches NO Meta object.

A read-only evidence step: the operator reviews the row-level list before it is uploaded. The
extraction lives in adbot.paid_list and is shared with scripts/build_lookalike_paid_list.py, so
what is audited here is by construction the same set that gets uploaded there — only the country
filter differs, and the country column is right there in the output to make that visible.

Option B exclusions (both Refund tabs + VIP upgrade RM88) come from adbot.paid_list.EXCLUDED_GIDS.

OUTPUT
------
Two tabs written back into the SOURCE workbook:
    "AUDIT · SG only"      — rows whose phone is +65, i.e. exactly what the SG seed uploads
    "AUDIT · All markets"  — every row that survived the exclusions, with its country
It writes there rather than creating a new file because the service account owns no Drive
storage — spreadsheets().create() returns 403 "The caller does not have permission". The source
workbook is already shared with it and already belongs to the operator, so this needs no storage
and no extra sharing step, and it already holds this exact customer data.

Nothing raw is logged here, written to state/, or committed — this repo is public.
"""
from __future__ import annotations

from typing import Any, Dict, List

from adbot import paid_list
from adbot.clients.drive import build_credentials
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

# Shared with the extractor, which skips tabs by this prefix so its own output never feeds back in.
AUDIT_PREFIX = paid_list.AUDIT_TAB_PREFIX
HEAD = ["Source Tab", "Name", "Email", "Phone (normalised)", "Country", "Country code"]


def main() -> None:
    log = get_logger()
    s = load_settings()
    sid = s.cpa.spreadsheet_id
    if not sid:
        raise SystemExit("!! cpa.spreadsheet_id is not configured")

    from googleapiclient.discovery import build  # lazy
    sheets = build("sheets", "v4", credentials=build_credentials(s.secrets.google_sa_json),
                   cache_discovery=False)

    rows, kept, excluded = paid_list.extract(sheets, sid, log)
    if not rows:
        raise SystemExit("!! nothing to audit — refusing to write an empty sheet")
    tally = paid_list.tally(rows)
    sg = [r for r in rows if r.country == "SG"]

    log.info("═" * 88)
    log.info("%d paid tab(s) kept, %d excluded → %d unique row(s)", kept, excluded, len(rows))
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        log.info("   %-8s %5d", k, v)
    inferred = [r for r in sg if r.cc == "inferred"]
    log.info("SG-only rows: %d  (%d carried +65 explicitly, %d had 65 INFERRED from a bare "
             "8-digit number)", len(sg), len(sg) - len(inferred), len(inferred))
    if inferred:
        # Hong Kong mobiles are also 8 digits and begin 5/6/9, so an inferred row is not proof of
        # a Singapore customer. Sort the sheet by "Country code" to review these first.
        log.warning("   ⚠ %d SG row(s) are INFERRED, not confirmed — a Hong Kong mobile typed "
                    "without +852 is indistinguishable from a Singapore one", len(inferred))
    if len(sg) < 100:
        log.warning("!! SG-only is %d, under Meta's 100-matched-person floor — an SG-only seed "
                    "could not build a lookalike", len(sg))

    out: Dict[str, List[List[str]]] = {
        f"{AUDIT_PREFIX} SG only": [HEAD] + [list(r) for r in sg],
        f"{AUDIT_PREFIX} All markets": [HEAD] + [list(r) for r in rows],
    }
    meta = sheets.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties").execute()
    existing = {p["properties"]["title"]: int(p["properties"]["sheetId"]) for p in meta["sheets"]}
    # Replace rather than append: a stale audit tab beside a fresh one is how somebody reviews
    # last week's list and approves the wrong seed.
    reqs: List[Dict[str, Any]] = [{"deleteSheet": {"sheetId": existing[n]}}
                                  for n in out if n in existing]
    reqs += [{"addSheet": {"properties": {"title": n}}} for n in out]
    sheets.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}).execute()
    sheets.spreadsheets().values().batchUpdate(spreadsheetId=sid, body={
        "valueInputOption": "RAW",       # RAW keeps phones as the text they are
        "data": [{"range": f"'{n}'!A1", "values": v} for n, v in out.items()]}).execute()

    url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    log.info("audit tabs written into the source workbook: %s", url)
    final_summary(
        log, f"AUDIT ONLY — no Meta object was created, updated or deleted. {excluded} tab(s) "
             f"excluded (both refund tabs + VIP upgrade RM88), leaving {len(rows)} unique rows "
             f"across {kept} paid tab(s), of which {len(sg)} are SG (+65). Country comes from the "
             f"dialling code; rows with no phone are 'unknown', not assumed SG. Review the two "
             f"'{AUDIT_PREFIX}' tabs in {url}")


if __name__ == "__main__":
    main()
