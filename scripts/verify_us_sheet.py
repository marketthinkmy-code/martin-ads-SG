"""Read-only: list every tab of the shared 'Paid Student List' spreadsheet,
locate the US tab (gid=1292000535), and confirm the CPA gate can parse it
(header detection + sample rows). Needed to wire config.california.yaml's
cpa.sales_tab to the correct TAB NAME (config wants the name, not the gid).
"""
from __future__ import annotations

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings

SPREADSHEET = "1DsKtcDpsWp3Njfah6Fw3PBizhGiy017ULw5qKeV-RSA"   # same file SG already uses
US_GID = 1292000535                                            # tab the operator pointed at


def main() -> None:
    s = load_settings()
    sc = SheetsClient(s.secrets.google_sa_json)

    meta = sc._svc.spreadsheets().get(
        spreadsheetId=SPREADSHEET, fields="sheets.properties").execute()
    print("Tabs in the spreadsheet (gid · title · rows·cols):")
    us_title = None
    for sh in meta.get("sheets", []):
        p = sh["properties"]
        gid, title = p.get("sheetId"), p.get("title")
        gp = p.get("gridProperties", {})
        mark = ""
        if gid == US_GID:
            us_title, mark = title, "   ← US tab (gid match)"
        print(f"  {gid:>12} · {title!r} · {gp.get('rowCount')}x{gp.get('columnCount')}{mark}")

    if not us_title:
        print(f"\n!! no tab with gid={US_GID} — check access / gid")
        return

    print(f"\n== US tab resolved: {us_title!r} ==")
    rows = sc.read_tab(SPREADSHEET, us_title)
    print(f"rows returned: {len(rows)}")
    if not rows:
        print("!! tab is empty or SA lacks access")
        return

    hdr_idx = -1
    for i, row in enumerate(rows[:10]):
        cols = cpa.find_columns(row)
        print(f"  row#{i}: find_columns -> {cols}")
        if cols.get("ad", -1) >= 0 or cols.get("campaign", -1) >= 0 or cols.get("adset", -1) >= 0:
            hdr_idx = i
            print(f"    ↳ looks like the HEADER row: {[c[:16] for c in row[:16]]}")
            break

    print("\nfirst data rows (first 16 cols, truncated):")
    start = (hdr_idx + 1) if hdr_idx >= 0 else 1
    for row in rows[start:start + 4]:
        print("   ", [c[:16] for c in row[:16]])

    print(f"\nTotal data rows (excl header): {len(rows) - (hdr_idx + 1 if hdr_idx >= 0 else 0)}")


if __name__ == "__main__":
    main()
