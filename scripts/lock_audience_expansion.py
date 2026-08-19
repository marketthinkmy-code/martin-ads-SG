"""Turn OFF every audience-expansion switch on the LAL band and retargeting ad sets.

WHY THIS EXISTS
---------------
Both new test campaigns were built asking Meta not to expand past their audience, and both came
back from the API expanded anyway — by two different mechanisms, which is why one check would
have missed the other:

  · The five 1-5-3 band ad sets were created with targeting_automation.advantage_audience = 0 and
    Meta STORED 1, together with individual_setting {age:1, gender:1} and an age_range of 35-65
    that was never requested. Sending the field is not the same as it being honoured.
  · The retargeting ad set did keep advantage_audience = 0, but Meta added
    targeting_relaxation_types.custom_audience = 1 and an expanded_implicit_custom_audiences entry
    — a hidden 1% lookalike of the video viewers. Different switch, same outcome.

Left alone, neither campaign measures what it was built to measure. The band test cannot attribute
a result to a band if every band is allowed to drift into the others, and a 5,000-person
retargeting pool on RM50/day would spend most of its budget outside the pool.

WHAT IT DOES
------------
For each ad set: read the current targeting, rebuild it from writable fields only, force both
switches off, and write it back. Read-only mirrors (effective_*, page_types, dt_consolidation_state,
age_range) are dropped rather than echoed — posting them back is rejected or silently re-derived.
Audience references are reduced to bare ids because Meta returns them hydrated with names and
rules that are not valid input.

Verification is not optional here: the whole point is that Meta already ignored this setting once,
so the script re-reads each ad set afterwards and reports what actually stuck rather than what was
sent. If a value refuses to hold, that is reported as a failure to escalate, not smoothed over.

Everything stays PAUSED — this only edits targeting.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ADSETS: List[Dict[str, str]] = [
    {"id": "120257761613910093", "label": "LAL 1%"},
    {"id": "120257761615520093", "label": "LAL 1-2%"},
    {"id": "120257761616950093", "label": "LAL 2-3%"},
    {"id": "120257761619130093", "label": "LAL 3-4%"},
    {"id": "120257761621230093", "label": "LAL 4-5%"},
    {"id": "120257762101050093", "label": "30d VV50 retarget"},
]

# Only these come back out of a GET in a form Meta will accept on a POST. Everything else is a
# read-only mirror (effective_*), a derived field (age_range, page_types) or hydrated objects.
WRITABLE = [
    "geo_locations", "age_min", "age_max", "genders", "locales", "flexible_spec",
    "publisher_platforms", "facebook_positions", "instagram_positions",
    "messenger_positions", "audience_network_positions", "device_platforms",
    "excluded_publisher_categories", "brand_safety_content_filter_levels",
]
AUDIENCE_KEYS = ["custom_audiences", "excluded_custom_audiences"]


def clean(t: Dict[str, Any]) -> Dict[str, Any]:
    spec: Dict[str, Any] = {k: t[k] for k in WRITABLE if t.get(k) not in (None, [], {})}
    for k in AUDIENCE_KEYS:
        if t.get(k):
            # Meta returns these hydrated with name/rule/data_source; only the id is valid input.
            spec[k] = [{"id": str(a["id"])} for a in t[k] if a.get("id")]
    # Meta emits instagram_positions containing explore_home without explore, then rejects that
    # same list on the way back in: "To place ads in Instagram Explore home, please also select
    # Instagram Explore." Valid as output, invalid as input — so repair it rather than echo it.
    ig = list(spec.get("instagram_positions") or [])
    if "explore_home" in ig and "explore" not in ig:
        ig.insert(ig.index("explore_home"), "explore")
        spec["instagram_positions"] = ig
    # Both switches, explicitly off.
    spec["targeting_automation"] = {"advantage_audience": 0}
    spec["targeting_relaxation_types"] = {"custom_audience": 0, "lookalike": 0}
    return spec


def read(g, adset_id: str) -> Dict[str, Any]:
    return g._request("GET", adset_id, params={"fields": "name,targeting"}).get("targeting") or {}


def flags(t: Dict[str, Any]) -> str:
    adv = (t.get("targeting_automation") or {}).get("advantage_audience")
    rel = t.get("targeting_relaxation_types") or {}
    exp = len(t.get("expanded_implicit_custom_audiences") or [])
    return (f"advantage_audience={adv} · relaxation.custom_audience={rel.get('custom_audience')}"
            f" · relaxation.lookalike={rel.get('lookalike')} · hidden_expansions={exp}")


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    summary: List[str] = []
    # Two failure modes that must not be conflated: the write itself being rejected (our bug,
    # fixable) versus Meta accepting the write and storing a different value (their override,
    # only fixable by hand). Reporting them as one thing sent the wrong diagnosis last run.
    errored: List[str] = []
    overridden: List[str] = []
    for a in ADSETS:
        log.info("═" * 88)
        before = read(g, a["id"])
        log.info("── %-20s %s", a["label"], a["id"])
        log.info("   before: %s", flags(before))

        try:
            g._request("POST", a["id"], data={"targeting": json.dumps(clean(before))})
        except Exception as exc:                                   # noqa: BLE001
            log.error("   !! update REJECTED: %s", exc)
            summary.append(f"  ✗ {a['label']:20} write rejected: {exc}")
            errored.append(a["label"])
            continue

        after = read(g, a["id"])
        log.info("   after:  %s", flags(after))
        adv_ok = int((after.get("targeting_automation") or {}).get("advantage_audience", 1)) == 0
        rel_ok = int((after.get("targeting_relaxation_types") or {}).get("custom_audience", 1)) == 0
        if adv_ok and rel_ok:
            summary.append(f"  ✓ {a['label']:20} expansion off")
        else:
            # Meta silently re-enabling this is exactly the failure that prompted the script, so
            # it is reported rather than assumed fixed.
            log.error("   !! write ACCEPTED but Meta stored a different value "
                      "(adv_ok=%s rel_ok=%s)", adv_ok, rel_ok)
            summary.append(f"  ✗ {a['label']:20} Meta OVERRODE the setting "
                           f"(advantage_audience ok={adv_ok}, relaxation ok={rel_ok})")
            overridden.append(a["label"])

    log.info("═" * 88)
    for line in summary:
        log.info(line)

    parts: List[str] = []
    ok = len(ADSETS) - len(errored) - len(overridden)
    parts.append(f"Expansion verified OFF on {ok}/{len(ADSETS)} ad set(s) — re-read after writing, "
                 f"so these are stored values rather than what was sent.")
    if errored:
        parts.append(f"‼ {len(errored)} write(s) were REJECTED and nothing changed on them "
                     f"({', '.join(errored)}) — that is a bug in this script's request, not a Meta "
                     f"policy decision, so it is fixable here and worth retrying.")
    if overridden:
        parts.append(f"‼ {len(overridden)} ad set(s) accepted the write and then stored a "
                     f"different value ({', '.join(overridden)}) — Meta is forcing audience "
                     f"expansion. Those ad sets cannot answer the question they were built to ask: "
                     f"the bands will bleed into each other. Turn Advantage+ audience off by hand "
                     f"in Ads Manager before activating, or accept the comparison is not clean.")
    final_summary(log, " ".join(parts))


if __name__ == "__main__":
    main()
