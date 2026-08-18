"""Build a fresh "Cust Paid List" customer audience from the paid sheet + its lookalikes.

The account's existing lookalikes off the paid list (120246547112550093 and friends) were built
2026-03-22 and are five months stale. This rebuilds the seed from the live sheet and derives new
lookalikes from it.

WHICH ROWS SEED IT
------------------
The Paid Student List spreadsheet holds ~19 tabs mixing REGISTRATION (lead) tabs and PAID tabs
across SG / MY / US / HK / TW. Tabs are classified by their own header row rather than by title,
because titles get renamed and a mis-picked tab would seed the lookalike on leads instead of
buyers: a tab is PAID when its header carries one of
    Item purchase · Purchase amount · 付費管道 · Transaction Id · Amount
Within a PAID tab the email and phone columns are located from that tab's own header too — the
tabs genuinely disagree on column order (some are Name|Email|Phone, others Name|付費管道|email|
whatsapp 號碼), so fixed indices would silently read the wrong column.

The seed is ALL markets, not SG only, and that is deliberate. Filtering to +65 leaves ~197 unique
phones; after Meta's typical 50-70% match rate that lands near the 100-person hard floor, far under
the 1,000-5,000 Meta wants for a stable lookalike. All markets gives ~838 phones / ~720 emails.
The lookalike is still TARGETED at SG (lookalike_spec.country) — only the seed is international,
which is exactly what allow_international_seeds is for. The customer avatar is the same
Chinese-speaking parent in every one of these markets, so the seed stays coherent.

PII HANDLING
------------
Emails and phones are normalised and SHA-256 hashed ON THIS RUNNER before any network call, so
only digests leave the process. Nothing raw is logged, written to state/, or committed — the logs
carry counts only. Phones are normalised to digits with a country code (a bare 8-digit SG mobile
gets 65 prepended, otherwise Meta cannot match it).

Idempotent-ish: the seed audience id is cached in state/entities_lookalike_paid.json, so a
re-dispatch re-uploads into the SAME audience (an upload is an upsert, so re-running is harmless
and is in fact how you refresh the list) rather than creating a second one. Lookalikes are only
created when absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from adbot.clients.drive import build_credentials
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_lookalike_paid.json"
SEED_NAME = "Cust Paid List"
TARGET_COUNTRY = "SG"
# (starting_ratio, ratio). starting_ratio None = a plain top-N% audience; a pair = a RANGE
# audience covering that band, which is what Meta calls "1% to 5%" and what the account's older
# "Lookalike (SG, 1% to 2%)" audiences are. A range excludes the tighter band below it, so 1%-5%
# does NOT overlap a separate 1% audience — they can run side by side without bidding against
# each other for the same people.
LOOKALIKES = [(None, 0.01), (None, 0.03), (0.01, 0.05)]
BATCH = 500                              # rows per upload call; Meta allows 10k, 500 keeps errors legible

PAID_HEADER = re.compile(r"(Item purchase|Purchase amount|付費管道|Transaction Id|Amount)", re.I)
EMAIL_COL = re.compile(r"mail", re.I)
PHONE_COL = re.compile(r"phone|whatsapp|號碼|号码", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sha256(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def norm_email(v: str) -> str:
    v = (v or "").strip().lower().replace("\\", "")
    return v if EMAIL_RE.match(v) else ""


def norm_phone(v: str) -> str:
    """Digits only, with a country code — Meta cannot match a bare local number."""
    d = re.sub(r"\D", "", (v or "").replace("\\", ""))
    if not d:
        return ""
    if len(d) == 8 and d[0] in "89":     # bare SG mobile written without +65
        d = "65" + d
    return d if 8 <= len(d) <= 15 else ""


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    sid = s.cpa.spreadsheet_id
    if not sid:
        raise SystemExit("!! cpa.spreadsheet_id is not configured")

    from googleapiclient.discovery import build  # lazy
    svc = build("sheets", "v4", credentials=build_credentials(s.secrets.google_sa_json),
                cache_discovery=False)

    meta = svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties").execute()
    tabs = [(p["properties"]["title"], p["properties"]["sheetId"]) for p in meta["sheets"]]
    log.info("spreadsheet has %d tab(s)", len(tabs))

    pairs: Set[Tuple[str, str]] = set()
    paid_tabs = 0
    for title, gid in tabs:
        try:
            values = (svc.spreadsheets().values()
                      .get(spreadsheetId=sid, range=f"'{title}'",
                           valueRenderOption="FORMATTED_VALUE",
                           dateTimeRenderOption="FORMATTED_STRING").execute()).get("values", [])
        except Exception as exc:                                    # noqa: BLE001
            log.warning("   ! could not read tab %r (gid %s): %s", title, gid, exc)
            continue
        if not values:
            continue
        # The header is rarely row 0 (tabs carry title/spacer rows), so find the first row that
        # names a contact column; that row also decides whether the tab is paid.
        hdr_i = next((i for i, r in enumerate(values[:10])
                      if any(EMAIL_COL.search(c or "") for c in r)
                      and any(PHONE_COL.search(c or "") for c in r)), None)
        if hdr_i is None:
            log.info("   · %-44s gid=%-12s no contact columns — skipped", title[:44], gid)
            continue
        hdr = values[hdr_i]
        if not PAID_HEADER.search(" | ".join(hdr)):
            log.info("   · %-44s gid=%-12s LEAD tab — skipped", title[:44], gid)
            continue
        ei = next((k for k, c in enumerate(hdr) if EMAIL_COL.search(c or "")), None)
        pi = next((k for k, c in enumerate(hdr) if PHONE_COL.search(c or "")), None)
        before = len(pairs)
        for row in values[hdr_i + 1:]:
            em = norm_email(row[ei]) if ei is not None and ei < len(row) else ""
            ph = norm_phone(row[pi]) if pi is not None and pi < len(row) else ""
            if em or ph:
                pairs.add((em, ph))
        paid_tabs += 1
        log.info("   ✔ %-44s gid=%-12s PAID  +%d new contact(s)", title[:44], gid, len(pairs) - before)

    if not pairs:
        raise SystemExit("!! no paid contacts found — refusing to create an empty audience")
    n_em = sum(1 for e, _ in pairs if e)
    n_ph = sum(1 for _, p in pairs if p)
    log.info("═" * 88)
    log.info("%d paid tab(s) → %d unique contact row(s): %d with email, %d with phone",
             paid_tabs, len(pairs), n_em, n_ph)
    if len(pairs) < 100:
        raise SystemExit(f"!! only {len(pairs)} contacts — Meta needs >=100 matched people for a "
                         f"lookalike; refusing to build one that cannot deliver")

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    # 1) seed audience ───────────────────────────────────────────────────────────────
    seed_id = st.get("seed_audience_id")
    if seed_id:
        log.info("reusing seed audience %s (upload is an upsert — this refreshes it)", seed_id)
    else:
        seed_id = g._request("POST", f"{acct}/customaudiences", data={
            "name": SEED_NAME,
            "subtype": "CUSTOM",
            "customer_file_source": "USER_PROVIDED_ONLY",
            "description": "Paid students across all markets, rebuilt from the Paid Student List "
                           "spreadsheet. Seeds the SG lookalikes.",
        })["id"]
        st["seed_audience_id"] = seed_id
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("+ seed audience %s %r", seed_id, SEED_NAME)

    # 2) upload hashed rows ──────────────────────────────────────────────────────────
    rows: List[List[str]] = [[sha256(e) if e else "", sha256(p) if p else ""] for e, p in sorted(pairs)]
    sent = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        g._request("POST", f"{seed_id}/users", data={"payload": json.dumps(
            {"schema": ["EMAIL", "PHONE"], "data": chunk})})
        sent += len(chunk)
        log.info("   ↑ uploaded %d/%d hashed row(s)", sent, len(rows))

    # 3) lookalikes ──────────────────────────────────────────────────────────────────
    lals: Dict[str, str] = st.get("lookalikes", {})
    made = []
    for start, ratio in LOOKALIKES:
        # Keep the old single-ratio key shape so audiences built before ranges existed are still
        # recognised as already-created and are not duplicated on this run.
        key = f"{ratio:.2f}" if start is None else f"{start:.2f}-{ratio:.2f}"
        band = f"{int(ratio*100)}%" if start is None else f"{int(start*100)}% to {int(ratio*100)}%"
        if lals.get(key):
            log.info("   · lookalike %s already exists (%s)", band, lals[key])
            continue
        name = f"Lookalike ({TARGET_COUNTRY}, {band}) - {SEED_NAME}"
        spec = {"ratio": ratio, "country": TARGET_COUNTRY, "allow_international_seeds": True}
        if start is not None:
            spec["starting_ratio"] = start
        try:
            lal_id = g._request("POST", f"{acct}/customaudiences", data={
                "name": name, "subtype": "LOOKALIKE", "origin_audience_id": seed_id,
                "lookalike_spec": json.dumps(spec),
            })["id"]
        except Exception as exc:                                    # noqa: BLE001
            # A lookalike fails when the seed has not finished matching yet. That is expected on a
            # first run and is NOT a reason to lose the seed — report it and let a re-dispatch add it.
            log.warning("   !! lookalike %s failed (seed may still be matching): %s", band, exc)
            continue
        lals[key] = lal_id
        st["lookalikes"] = lals
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        made.append(f"{band}={lal_id}")
        log.info("   + lookalike %s → %s", name, lal_id)

    log.info("═" * 88)
    final_summary(
        log, f"Seed audience {SEED_NAME} ({seed_id}) refreshed with {len(rows)} hashed contacts "
             f"from {paid_tabs} paid tab(s) — all markets, since an SG-only seed (~197) is below "
             f"what Meta can model. Lookalikes targeted at {TARGET_COUNTRY}: "
             f"{', '.join(made) if made else 'none created this run'}. Meta takes a few hours to "
             f"match the list and size the lookalikes; they are unusable until then. Emails and "
             f"phones were SHA-256 hashed on this runner — nothing raw was logged or stored.")


if __name__ == "__main__":
    main()
