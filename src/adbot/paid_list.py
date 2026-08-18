"""Extract paid customers from the Paid Student List spreadsheet.

This lives in one place on purpose. The operator audits a row-level export and then approves an
upload; if the audit script and the upload script each carried their own copy of this logic they
could drift, and an approved audit would stop being evidence for what actually got uploaded.
Both callers import from here so the two lists are the same list by construction.

TAB CLASSIFICATION
------------------
The workbook holds ~28 tabs mixing REGISTRATION (lead) tabs with PAID tabs across SG/MY/US/HK/TW.
Tabs are classified by their own header row rather than by title, because titles get renamed and
a mis-picked tab would seed a lookalike on leads instead of buyers. A tab is PAID when its header
carries one of:  Item purchase · Purchase amount · 付費管道 · Transaction Id · Amount

Email and phone columns are located from each tab's own header for the same reason — the tabs
genuinely disagree on column order (Name|Email|Phone versus Name|付費管道|email|whatsapp 號碼),
so fixed indices would silently read the wrong column and upload garbage.

EXCLUDED_GIDS is the operator's reviewed exclusion list (option B), by gid rather than by title:
  · Refund / US Refund — people who bought and then took their money back. They were swept in
    originally because their headers carry an "Amount" column, and seeding a lookalike on them
    asks Meta to go find more people who will refund.
  · VIP upgrade (RM88) — a different tier from an RM1997/RM18k buyer, and at 512 rows it was 26%
    of the seed, diluting the high-value signal.

COUNTRY
-------
Derived from the phone's dialling code, the same +65 rule the CPA layer uses to isolate SG sales.
A row with no phone is "unknown", NEVER assumed SG — guessing there is the one error that would
make an "SG only" seed silently wrong.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, NamedTuple, Set, Tuple

PAID_HEADER = re.compile(r"(Item purchase|Purchase amount|付費管道|Transaction Id|Amount)", re.I)
EMAIL_COL = re.compile(r"mail", re.I)
PHONE_COL = re.compile(r"phone|whatsapp|號碼|号码", re.I)
NAME_COL = re.compile(r"^\s*(name|名字|姓名)\s*$", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The audit export writes its tabs back into this same workbook, so the extractor can read its
# own output. Those tabs are skipped today only because they carry no PAID marker column —
# incidental, not by design. Skipping them by title makes it deliberate: add an "Amount" column
# to the audit output some day and without this the list would silently feed back into itself.
AUDIT_TAB_PREFIX = "AUDIT ·"

EXCLUDED_GIDS: Dict[int, str] = {
    1847972349: "Refund — bought then refunded",
    254146896:  "US Refund — bought then refunded",
    697093187:  "VIP upgrade (RM88) — different tier, was 26% of the seed",
}


class Row(NamedTuple):
    source_tab: str
    name: str
    email: str
    phone: str
    country: str
    cc: str          # how the country code was obtained: "explicit" | "inferred" | "none"


def norm_email(v: str) -> str:
    v = (v or "").strip().lower().replace("\\", "")
    return v if EMAIL_RE.match(v) else ""


def norm_phone(v: str) -> Tuple[str, str]:
    """(digits-with-country-code, how the code was obtained). Meta cannot match a bare number.

    Returns cc as "explicit" when the row already carried a country code, "inferred" when 65 was
    prepended to a bare 8-digit number, and "none" when there is no usable phone.

    The inference is a real hazard for an SG-only seed and is flagged rather than hidden: an
    8-digit number beginning 8 or 9 is a Singapore mobile, but Hong Kong mobiles are ALSO 8 digits
    and begin 5, 6 or 9. So a Hong Kong buyer whose number was typed without +852 becomes
    indistinguishable from a Singaporean one. Callers that care about purity can drop inferred
    rows; the audit export shows the flag so the size of the problem is visible before deciding.
    """
    d = re.sub(r"\D", "", (v or "").replace("\\", ""))
    if not d:
        return "", "none"
    if len(d) == 8 and d[0] in "89":          # bare local mobile — assume SG, but say so
        return "65" + d, "inferred"
    return (d, "explicit") if 8 <= len(d) <= 15 else ("", "none")


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


def extract(sheets, spreadsheet_id: str, log) -> Tuple[List[Row], int, int]:
    """Every unique paid contact in the workbook, minus EXCLUDED_GIDS.

    Returns (rows, paid_tabs_kept, tabs_excluded). Deduplication is on (email, phone) so the same
    customer appearing in several tabs is counted once. Nothing raw is logged — counts only.
    """
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id,
                                     fields="sheets.properties").execute()
    tabs = [(p["properties"]["title"], int(p["properties"]["sheetId"])) for p in meta["sheets"]]
    log.info("spreadsheet has %d tab(s)", len(tabs))

    seen: Set[Tuple[str, str]] = set()
    rows: List[Row] = []
    kept = excluded = 0
    for title, gid in tabs:
        if title.startswith(AUDIT_TAB_PREFIX):
            log.info("   · %-40s gid=%-12s this script's own output — skipped", title[:40], gid)
            continue
        try:
            values = (sheets.spreadsheets().values()
                      .get(spreadsheetId=spreadsheet_id, range=f"'{title}'",
                           valueRenderOption="FORMATTED_VALUE",
                           dateTimeRenderOption="FORMATTED_STRING").execute()).get("values", [])
        except Exception as exc:                                   # noqa: BLE001
            log.warning("   ! could not read %r (gid %s): %s", title, gid, exc)
            continue
        if not values:
            continue
        # The header is rarely row 0 (tabs carry title/spacer rows), so find the first row that
        # names a contact column; that row also decides whether the tab is paid.
        hdr_i = next((i for i, r in enumerate(values[:10])
                      if any(EMAIL_COL.search(c or "") for c in r)
                      and any(PHONE_COL.search(c or "") for c in r)), None)
        if hdr_i is None:
            continue
        hdr = values[hdr_i]
        if not PAID_HEADER.search(" | ".join(hdr)):
            log.info("   · %-40s gid=%-12s LEAD tab — skipped", title[:40], gid)
            continue
        if gid in EXCLUDED_GIDS:
            excluded += 1
            log.info("   ⛔ %-40s gid=%-12s EXCLUDED — %s", title[:40], gid, EXCLUDED_GIDS[gid])
            continue
        ei = next((k for k, c in enumerate(hdr) if EMAIL_COL.search(c or "")), None)
        pi = next((k for k, c in enumerate(hdr) if PHONE_COL.search(c or "")), None)
        ni = next((k for k, c in enumerate(hdr) if NAME_COL.match(c or "")), None)
        before = len(rows)
        for r in values[hdr_i + 1:]:
            em = norm_email(r[ei]) if ei is not None and ei < len(r) else ""
            ph, cc = norm_phone(r[pi]) if pi is not None and pi < len(r) else ("", "none")
            if not (em or ph) or (em, ph) in seen:
                continue
            seen.add((em, ph))
            nm = r[ni].strip() if ni is not None and ni < len(r) else ""
            rows.append(Row(title, nm, em, ph, country_of(ph), cc))
        kept += 1
        log.info("   ✔ %-40s gid=%-12s +%d row(s)", title[:40], gid, len(rows) - before)
    return rows, kept, excluded


def tally(rows: List[Row]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r.country] = out.get(r.country, 0) + 1
    return out
