"""CPA (cost per real paid acquisition) attribution from the Paid Student List.

Each sales row carries the UTM (campaign / ad set / ad name) that drove a paid enrolment
plus a created date. We parse the tab by *header name* (robust to column reordering),
normalise the UTM values for matching against Meta entity names, and window sales by date
(14 / 30 / 60 days + lifetime). Joining Meta spend then yields CPA; the tiers below encode
the operator's KPI. Pure functions only — no I/O — so this is fully unit-tested.
"""
from __future__ import annotations

import calendar
import datetime as dt
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple

WINDOWS = (14, 30, 60)  # rolling day windows; lifetime is handled separately

# decision tiers (reason codes)
KEEP = "cpa_keep"
MONITOR = "cpa_monitor"
PAUSE_CANDIDATE = "cpa_pause_candidate"
HARD_STOP = "cpa_hard_stop"
NO_SALES = "cpa_no_sales"


def norm(s: str) -> str:
    """Normalise a UTM/name value for matching: unescape, collapse whitespace, casefold."""
    s = (s or "").replace("\\", "")
    return " ".join(s.split()).casefold()


def ad_key(s: str) -> str:
    """Punctuation/width-robust key for matching an ad NAME between the sheet's UTM
    value and a Meta ad name. NFKC-folds full-width→half-width, casefolds, and drops
    ALL whitespace + punctuation (keeps only alphanumerics + CJK). So the same creative
    matches even when one side used a full-width colon or extra spaces:
    'MAR Video 5: 林書豪 story'  and  'mar video 5：林書豪story'  →  'marvideo5林書豪story'.
    """
    s = unicodedata.normalize("NFKC", (s or "").replace("\\", "")).casefold()
    return re.sub(r"[\W_]+", "", s)


def _hkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def find_columns(header: List[str]) -> Dict[str, int]:
    """Locate date / campaign / adset / ad / amount columns by fuzzy header match."""
    keys = [_hkey(h) for h in header]

    def first(*needles_in_order) -> int:
        for needle in needles_in_order:                 # exact-ish matches first
            for i, k in enumerate(keys):
                if k == needle:
                    return i
        for needle in needles_in_order:                 # then substring
            for i, k in enumerate(keys):
                if needle in k:
                    return i
        return -1

    date = first("createddate", "date")
    if date < 0:                          # Chinese date headers (報名日期) get stripped to "" by _hkey
        low = [(h or "").strip().lower() for h in header]
        for zh in ("報名日期", "报名日期", "報名", "报名", "購買日期", "购买日期", "付款日期", "成交日期"):
            hit = next((i for i, h in enumerate(low) if zh in h), -1)
            if hit >= 0:
                date = hit
                break
    return {
        "date": date,
        # "campaignname"/"campaign" also catch the SG tab's "Campaign Name" header (no "UTM Campaign")
        "campaign": first("utmcampaign", "campaignname", "campaign"),
        "adset": first("utmadset", "utmadsset"),
        "ad": first("utmadname", "utmadsname"),
        "amount": first("purchaseamount", "amount"),
    }


_EMAIL_HDR = re.compile(r"mail", re.I)
_PHONE_HDR = re.compile(r"phone|mobile|whatsapp|電話|电话|號碼|号码|手機|手机", re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def person_columns(header: List[str]) -> Tuple[List[int], List[int]]:
    """(email column indexes, phone column indexes) by header text."""
    em = [i for i, h in enumerate(header) if _EMAIL_HDR.search(h or "")]
    ph = [i for i, h in enumerate(header) if _PHONE_HDR.search(h or "") and i not in em]
    return em, ph


def person_ids(row: List[str], email_cols: List[int], phone_cols: List[int]) -> FrozenSet[str]:
    """Identity tokens for one sheet row: lower-cased email, and the last 8 phone digits (so
    '+65 9123 4567', '6591234567' and '91234567' are the same person). Name alone is never used."""
    out = set()
    for i in email_cols:
        v = (row[i] if i < len(row) else "").strip().lower().replace("\\", "")
        if _EMAIL_RE.match(v):
            out.add("e:" + v)
    for i in phone_cols:
        d = re.sub(r"\D", "", row[i] if i < len(row) else "")
        if len(d) >= 8:
            out.add("p:" + d[-8:])
    return frozenset(out)


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})


def _safe(y: int, mo: int, d: int) -> Optional[dt.date]:
    y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def parse_date(s: str) -> Optional[dt.date]:
    """Tolerant date parser: ISO, D/M/Y & M/D/Y (/ - . separators, optional time), month
    names (14 Jan 2026 / Jan 14, 2026), and Google Sheets serial numbers."""
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)              # ISO 2026-01-14
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _safe(y, mo, d)
    m = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)           # D/M/Y or M/D/Y
    if m:
        a, b, y = (int(x) for x in m.groups())
        if a > 12 and b <= 12:
            return _safe(y, b, a)                                       # a is the day
        if b > 12 and a <= 12:
            return _safe(y, a, b)                                       # month-first
        return _safe(y, b, a) or _safe(y, a, b)                         # ambiguous -> day-first (MY)
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{2,4})", s)        # 14 Jan 2026
    if m and m.group(2).lower() in _MONTHS:
        return _safe(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{2,4})", s)        # Jan 14, 2026
    if m and m.group(1).lower() in _MONTHS:
        return _safe(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    if re.fullmatch(r"\d{4,6}", s):                                     # Sheets serial
        try:
            return dt.date(1899, 12, 30) + dt.timedelta(days=int(s))
        except (ValueError, OverflowError):
            return None
    return None


def _money(s: str, default: float) -> float:
    digits = re.sub(r"[^\d.]", "", s or "")
    try:
        val = float(digits)
        return val if val > 0 else default
    except ValueError:
        return default


@dataclass
class Sale:
    date: Optional[dt.date]
    campaign: str   # normalised
    adset: str      # normalised
    ad: str         # normalised
    amount: float
    ids: FrozenSet[str] = frozenset()   # who: "e:<email>" / "p:<last 8 phone digits>" (never logged)


def parse_sales(values: List[List[str]], default_price: float):
    """Find the header row, then parse data rows into Sale records.

    Returns (sales, columns, header_row). The header is the first of the top rows that
    exposes both a UTM campaign and a UTM ad column.
    """
    if not values:
        return [], {}, []
    header_idx, cols = 0, find_columns(values[0])
    for i, row in enumerate(values[:8]):
        candidate = find_columns(row)
        if candidate.get("campaign", -1) >= 0 and candidate.get("ad", -1) >= 0:
            header_idx, cols = i, candidate
            break
    header = values[header_idx]
    em_cols, ph_cols = person_columns(header)

    sales: List[Sale] = []
    for row in values[header_idx + 1:]:
        def cell(key: str) -> str:
            idx = cols.get(key, -1)
            return row[idx] if 0 <= idx < len(row) else ""

        campaign, ad = norm(cell("campaign")), norm(cell("ad"))
        if not campaign and not ad:
            continue
        sales.append(Sale(parse_date(cell("date")), campaign, norm(cell("adset")),
                          ad, _money(cell("amount"), default_price), person_ids(row, em_cols, ph_cols)))
    return sales, cols, header


def _full(s: Sale) -> bool:
    return bool(s.campaign and s.adset and s.ad)


def register_ad_for(sale: Sale, registers: List[Sale]) -> Optional[Sale]:
    """The Register row this buyer signed up through: same person (shared email or phone), all
    three UTM levels filled, the latest registration on or before the sale date (latest of all
    when none is dated before it). None when the buyer has no such Register row."""
    if not sale.ids:
        return None
    mine = [r for r in registers if _full(r) and r.ids & sale.ids]
    if not mine:
        return None
    before = [r for r in mine if r.date and sale.date and r.date <= sale.date]
    pool = before or mine
    return max(pool, key=lambda r: r.date or dt.date.min)


def sale_utms(sale: Sale, registers: List[Sale]) -> List[Tuple[str, str, str]]:
    """Every (campaign, ad set, ad) this sale credits, de-duplicated (19 Nov operator 「让 monitor
    认成交时，也看报名表上这个人是从哪支 ad 报名的…一定要看完 campaign、ad set、ad」): the Paid row's
    own UTM, plus the UTM of the buyer's registration in the Register tab. The Paid row's UTM can
    be missing or shifted (18 Nov: 'facebook mobile reels…' in the campaign column), so the
    Register row is what still ties the sale to the ad that brought the parent in. Only full
    three-level UTMs count; an ad name alone never does."""
    out: List[Tuple[str, str, str]] = []
    if _full(sale):
        out.append((sale.campaign, sale.adset, sale.ad))
    reg = register_ad_for(sale, registers)
    if reg is not None and (reg.campaign, reg.adset, reg.ad) not in out:
        out.append((reg.campaign, reg.adset, reg.ad))
    return out


def count_windows(sales: List[Sale], today: dt.date, windows=WINDOWS) -> Dict[str, int]:
    """Count sales in each rolling window plus lifetime (key 'life')."""
    out = {f"{w}d": 0 for w in windows}
    out["life"] = len(sales)
    for s in sales:
        if s.date is None:
            continue
        for w in windows:
            if s.date > today - dt.timedelta(days=w):
                out[f"{w}d"] += 1
    return out


def attribute(sales: List[Sale], today: dt.date, windows=WINDOWS):
    """Group sales by (campaign, adset, ad), by (campaign, adset), and by campaign."""
    by_ad: Dict[Tuple[str, str, str], List[Sale]] = {}
    by_adset: Dict[Tuple[str, str], List[Sale]] = {}
    by_campaign: Dict[str, List[Sale]] = {}
    for s in sales:
        by_ad.setdefault((s.campaign, s.adset, s.ad), []).append(s)
        by_adset.setdefault((s.campaign, s.adset), []).append(s)
        by_campaign.setdefault(s.campaign, []).append(s)
    counts = lambda groups: {k: count_windows(v, today, windows) for k, v in groups.items()}
    return counts(by_ad), counts(by_adset), counts(by_campaign)


def cpa(spend: float, sales_count: int):
    """Cost per acquisition; inf when there is spend but no sales, None when no spend."""
    if sales_count > 0:
        return spend / sales_count
    return math.inf if spend > 0 else None


@dataclass
class CpaTiers:
    healthy_max: float = 800.0
    max_acceptable: float = 960.0
    hard_stop: float = 1200.0


def cpa_tier(cpa_value, tiers: CpaTiers) -> str:
    """Map a CPA to a decision tier reason code."""
    if cpa_value is None:
        return NO_SALES          # no spend yet — not judgeable
    if cpa_value == math.inf:
        return NO_SALES          # spent, no sales (handled with min-spend/age elsewhere)
    if cpa_value <= tiers.healthy_max:
        return KEEP
    if cpa_value <= tiers.max_acceptable:
        return MONITOR
    if cpa_value <= tiers.hard_stop:
        return PAUSE_CANDIDATE
    return HARD_STOP


# combined CPA × CPL reason codes
CPL_RESCUED = "cpl_high_but_cpa_ok"   # over-CPL, but real sales at an acceptable CPA -> keep
CPA_IMMATURE = "cpa_immature"         # inside the conversion window -> no CPA judgement yet


def combined_decision(*, cpl_pause: bool, cpl_reason: str, cpa_value, cpa_sales: int,
                      cpa_spend: float, age_days, tiers: CpaTiers,
                      conversion_days: int = 14, min_spend: float = 0.0):
    """Fold real-sales CPA into the CPL pause decision — the operator's policy.

    1. Auto-pause on CPA only for a *proven* hard stop: real matched sales, finite CPA above
       the hard-stop line, past the conversion window, with enough spend. Zero matched sales
       never auto-pauses on CPA (it may be an attribution gap, not true waste).
    2. CPA *rescues* an ad the CPL guardrail would pause when it has real sales at CPA at or
       below the hard stop (still profitable against the ~RM2.4k price) — so registration
       cost alone never kills a money-making ad. Rescue ignores age: real sales are real.

    Returns (should_pause, reason).
    """
    finite_cpa = cpa_value is not None and cpa_value != math.inf
    matured = age_days is not None and age_days >= conversion_days and cpa_spend >= min_spend

    if cpa_sales > 0 and finite_cpa and cpa_value > tiers.hard_stop and matured:
        return True, HARD_STOP                       # proven too expensive
    if cpl_pause and cpa_sales > 0 and finite_cpa and cpa_value <= tiers.hard_stop:
        return False, CPL_RESCUED                    # real profitable sales protect it
    return cpl_pause, cpl_reason                      # otherwise the CPL decision stands
