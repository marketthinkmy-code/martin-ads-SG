"""Fix the Health & Wellness | 1-1-5 ad set's detailed targeting to the operator's exact
spec (screenshot 2026-07-30) — LIVE write.

Wanted inclusion (one detailed-targeting group, OR'd):
  Interests: Personal care · Health and wellness · Shopping · Physical fitness · Online
             shopping · Health and beauty · Physical exercise · Well-being · Wellness
  Behaviours: Engaged Shoppers

Meta needs the numeric interest/behavior IDs, not names. We resolve each name to an ID by
(1) HARVESTING it from the account's other ad sets (an interest has one global ID, so reusing
the account's own chosen ID is exact and unambiguous), then (2) falling back to Meta's
targeting search for anything not present in any ad set. We then overwrite the ad set's
targeting, preserving SG geo / exclusions / age / advantage-audience. Nothing is written unless
every one of the 9 interests + Engaged Shoppers resolves; otherwise we report and stop. Prints
the resolved id→name map for verification.
"""
from __future__ import annotations

import re

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

TARGET_ADSET = "120256984987300093"   # [SG] 儿童长高方程式 | Health & Wellness | 1-1-5

# (normalised-name, display) in screenshot order
WANT_INTERESTS = [
    ("personal care", "Personal care"),
    ("health and wellness", "Health and wellness"),
    ("shopping", "Shopping"),
    ("physical fitness", "Physical fitness"),
    ("online shopping", "Online shopping"),
    ("health and beauty", "Health and beauty"),
    ("physical exercise", "Physical exercise"),
    ("well-being", "Well-being"),
    ("wellness", "Wellness"),
]
WANT_BEHAVIOR = ("engaged shoppers", "Engaged Shoppers")
# disambiguation hint per interest (the parenthetical category in the screenshot), same order
HINTS = ["toiletries", "personal care", "retail", "fitness", "retail",
         "beauty", "fitness", "psychology", "personal care"]

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"}, {"id": "120246547080720093"}]


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    # 1) harvest interest/behavior id-by-name from every SG ad set ───────────────
    adsets = g._get_all(f"{acct}/adsets", {"fields": "targeting", "limit": 500})
    int_by_name, beh_by_name = {}, {}

    def grab(d):
        for i in (d.get("interests") or []):
            if i.get("id") and i.get("name"):
                int_by_name.setdefault(_norm(i["name"]), (str(i["id"]), i["name"]))
        for b in (d.get("behaviors") or []):
            if b.get("id") and b.get("name"):
                beh_by_name.setdefault(_norm(b["name"]), (str(b["id"]), b["name"]))

    for a in adsets:
        t = a.get("targeting") or {}
        grab(t)
        for grp in (t.get("flexible_spec") or []):
            grab(grp)
    log.info("harvested %d interests + %d behaviors from %d SG ad sets",
             len(int_by_name), len(beh_by_name), len(adsets))

    # 2) act_/targetingsearch (what Ads Manager uses) for anything not harvested ──
    def ts_search(q):
        try:
            rows = g._request("GET", f"{acct}/targetingsearch", params={"q": q, "limit": 100}).get("data", [])
        except Exception as e:  # noqa: BLE001
            log.warning("   targetingsearch(%r) failed: %s", q, e)
            return []
        return rows

    def _mk(s):  # punctuation-robust key: lowercase, &→and, drop non-alphanumerics
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower().replace("&", " and "))

    def _base(n):  # match on the name BEFORE the "(category)" Meta appends
        return _mk(re.sub(r"\(.*?\)", " ", n or ""))

    def _cat(r):  # searchable category text (the parenthetical + path + disambiguation)
        return _mk(str(r.get("disambiguation_category") or "") + " "
                   + " ".join(str(x) for x in (r.get("path") or [])) + " " + str(r.get("name") or ""))

    def resolve(disp, want_kind, hint=""):
        raw = ts_search(disp)
        typed = [r for r in raw if _norm(str(r.get("type") or "")).startswith(want_kind)] or raw
        cands = [r for r in typed if _base(r.get("name")) == _mk(disp)]
        log.info("   targetingsearch %-20s → %d raw / %d base-name match", disp, len(raw), len(cands))
        if not cands:
            for r in typed[:5]:
                log.info("      cand '%s' [%s]", r.get("name"), r.get("id"))
            return None
        hk = _mk(hint)
        best = (next((r for r in cands if hk and hk in _cat(r)), None)
                or max(cands, key=lambda r: r.get("audience_size_upper_bound") or r.get("audience_size") or 0))
        return (str(best["id"]), best["name"])

    interests, missing = [], []
    for (nm, disp), hint in zip(WANT_INTERESTS, HINTS):
        hit = int_by_name.get(nm) or resolve(disp, "interest", hint)
        if hit:
            interests.append({"id": hit[0], "name": hit[1]})
            log.info("✓ interest %-22s → %s (%s)", disp, hit[0], hit[1])
        else:
            missing.append(disp)
            log.error("✗ interest %-22s → NOT FOUND", disp)

    beh = beh_by_name.get(WANT_BEHAVIOR[0]) or resolve(WANT_BEHAVIOR[1], "behavior")
    behaviors = [{"id": beh[0], "name": beh[1]}] if beh else []
    if beh:
        log.info("✓ behavior %-22s → %s (%s)", WANT_BEHAVIOR[1], beh[0], beh[1])
    else:
        missing.append(WANT_BEHAVIOR[1])
        log.error("✗ behavior %-22s → NOT FOUND", WANT_BEHAVIOR[1])

    if missing:
        raise SystemExit(f"!! could not resolve {len(missing)} item(s): {missing} — nothing written. "
                         "Need their Meta IDs (add each once in Ads Manager so it can be harvested, "
                         "or provide the IDs).")

    # 3) preserve the ad set's current geo/age/advantage, swap in the new detailed targeting ──
    cur = g._request("GET", TARGET_ADSET, params={"fields": "name,targeting"})
    ct = cur.get("targeting") or {}
    adv = (ct.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv is None else int(adv)
    age_min = int(ct.get("age_min") or 25)
    age_max = int(ct.get("age_max") or 65)

    spec = {
        "geo_locations": SG_GEO, "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": SG_EXCL, "locales": [1004],
        "flexible_spec": [{"interests": interests, "behaviors": behaviors}],
    }
    import json as _json
    g._request("POST", TARGET_ADSET, data={"targeting": _json.dumps(spec)})
    log.info("═" * 88)
    log.info("✔ updated ad set %s ('%s')", TARGET_ADSET, cur.get("name"))
    log.info("   %d interests + %d behavior · age %s-%s · advantage_audience=%s · geo SG",
             len(interests), len(behaviors), age_min, age_max, adv)
    final_summary(log, "Health & Wellness | 1-1-5 targeting fixed to the operator's 9 interests + "
                       "Engaged Shoppers (still PAUSED). Review in Ads Manager, then activate.")


if __name__ == "__main__":
    main()
