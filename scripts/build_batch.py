"""Build a creative batch for ONE market from creatives/batch_2026_08.yaml.

Replaces the market-specific build_sg_batch.py: the copy, grouping and card order now live in the
YAML, and this script is the part that talks to Meta. Copy the pair (this file + the YAML) into
the MY or CAL repo and set ADBOT_MARKET — nothing else needs to change, and there is no second
copy of the copy to drift.

    ADBOT_MARKET=sg python scripts/build_batch.py          # default is sg
    ADBOT_BATCH_GROUPS=a_knowledge,b_myths ...             # redo only some groups

Grouping is by angle family and is load-bearing, not cosmetic: several creatives reuse the SAME
parent testimonial screenshots, so putting them in one ad set would make them bid against each
other with duplicate proof. The YAML's group layout keeps every mutually-exclusive pair apart.

Card order comes from the card_NN filenames. Five decks are split banners whose first two cards
are two halves of one wide image, so the order is locked rather than incidental — never re-sort.

Everything is created PAUSED.

⚠️ NOT idempotent across dispatches on a runner: resumability relies on state/, which is not
committed, so a fresh runner starts empty and a second dispatch would build a SECOND copy of
every campaign. Treat a build as one-shot; to fix already-built entities, write a targeted script.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from adbot import media
from adbot.build_1_1_10 import build
from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.creative_groups import CAROUSEL, SINGLE_IMAGE, VIDEO, Asset, Unit
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "creatives" / "batch_2026_08.yaml"

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]
KINDS = {"carousel": CAROUSEL, "single_image": SINGLE_IMAGE, "video": VIDEO}


def assemble(copy: Dict[str, Any], blocks: Dict[str, str]) -> str:
    """Body = the ad's own intro/closing wrapped in the market's four shared blocks."""
    parts = [copy["intro"].rstrip(), "", blocks["bio"], "",
             blocks["learn_lead"], copy.get("curriculum") or blocks["curriculum"], "",
             blocks["and_lead"], blocks["negatives"], ""]
    if copy.get("closing"):
        parts += [copy["closing"].rstrip(), ""]
    parts.append(blocks["cta"])
    return "\n".join(parts)


def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0
    cnt = lambda spec: sum(len(spec.get(k) or []) for k in DETAIL_KEYS)
    return cnt(t) + sum(cnt(grp) for grp in (t.get("flexible_spec") or []))


def clone_targeting(adsets: List[dict], name: str, s, geo: Dict[str, Any]
                    ) -> Tuple[Optional[dict], Optional[str]]:
    """Clone interest/behaviour targeting from the richest live ad set matching `name`."""
    key = name.strip().lower()
    matches = [a for a in adsets if (a.get("name") or "").strip().lower() == key] \
        or [a for a in adsets if key in (a.get("name") or "").strip().lower()]
    if not matches:
        return None, None
    best = max(matches, key=lambda a: _richness(a.get("targeting") or {}))
    t = best.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:      # Meta rejects a higher hard floor when Advantage+ is on
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": geo, "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": [{"id": i} for i in
                                      (s.meta.targeting.excluded_custom_audiences or [])],
        "locales": s.meta.targeting.locales or [1004],
    }
    if t.get("genders"):
        spec["genders"] = t["genders"]
    fs = t.get("flexible_spec")
    if fs:
        spec["flexible_spec"] = fs
    else:
        legacy = {k: t[k] for k in DETAIL_KEYS if t.get(k)}
        if legacy:
            spec["flexible_spec"] = [legacy]
    return spec, best.get("name")


def make_unit(ad: Dict[str, Any], assets_root: Path, content_id: str) -> Unit:
    folder = assets_root / ad["dir"]
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    kind = KINDS[ad["kind"]]
    if not files:
        raise SystemExit(f"no assets in {folder}")
    if kind != CAROUSEL and len(files) != 1:
        raise SystemExit(f"{ad['kind']} expects exactly 1 file, found {len(files)} in {folder}")
    if kind == CAROUSEL and not (2 <= len(files) <= 10):
        raise SystemExit(f"carousel needs 2–10 cards, found {len(files)} in {folder}")
    assets = [Asset(file_id=f"batch/{ad['dir']}/{p.name}", name=f"{ad['dir']}/{p.name}",
                    mime=mimetypes.guess_type(p.name)[0] or "image/jpeg", local_path=str(p))
              for p in files]
    return Unit(content_id=content_id, kind=kind, assets=assets)


def main() -> None:
    log = get_logger()
    market = (os.environ.get("ADBOT_MARKET") or "sg").strip().lower()
    spec_doc = yaml.safe_load(SPEC_PATH.read_text())
    if market not in spec_doc["markets"]:
        raise SystemExit(f"unknown market {market!r}; have {sorted(spec_doc['markets'])}")
    mk = spec_doc["markets"][market]
    blocks = mk["blocks"]

    # A market whose link/geo is still a placeholder must NOT build — 18 ads pointing at the
    # literal string "TODO_CAL_LANDING_PAGE" would be worse than a hard failure.
    todo = [k for k in ("link", "geo") if str(mk.get(k, "")).startswith("TODO_")]
    if todo:
        raise SystemExit(f"market {market!r} still has placeholder {todo} in {SPEC_PATH.name} — "
                         f"fill them in before building")

    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    s.naming.prefix = mk["naming_prefix"]
    s.meta.budget.level = "CAMPAIGN"
    s.meta.budget.daily_amount_myr = mk["daily_myr"]
    s.meta.lead_destination.link_url = mk["link"]
    geo = mk.get("geo") or {"countries": s.meta.targeting.countries}
    assets_root = ROOT / spec_doc["assets_root"]

    log.info("market=%s · prefix=%r · RM%s/day · link=%s", market, s.naming.prefix,
             mk["daily_myr"], mk["link"])

    only = {x.strip() for x in (os.environ.get("ADBOT_BATCH_GROUPS") or "").split(",") if x.strip()}
    if only:
        unknown = only - {g_["key"] for g_ in spec_doc["groups"]}
        if unknown:
            raise SystemExit(f"unknown group key(s): {sorted(unknown)}")
        log.info("group filter active → %s", sorted(only))

    adsets = g._get_all(f"{acct}/adsets", {"fields": "name,effective_status,targeting", "limit": 500})
    log.info("pulled %d ad sets for cloning", len(adsets))

    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for ad in spec_doc["ads"]:
        by_group.setdefault(ad["group"], []).append(ad)

    summary: List[str] = []
    total_ads = 0
    for grp in spec_doc["groups"]:
        if only and grp["key"] not in only:
            continue
        ads = by_group.get(grp["key"]) or []
        if not ads:
            continue
        label = grp["label"][market]
        log.info("═" * 88)
        log.info("── %s  (%d ads)", label, len(ads))

        spec, src = clone_targeting(adsets, grp["clone"], s, geo)
        if spec is None:
            log.error("!! no ad set like %r to clone — SKIPPING %s", grp["clone"], label)
            summary.append(f"  ⏭ SKIP {label} (no clone source {grp['clone']!r})")
            continue
        log.info("   targeting ← %r (age %s-%s · adv=%s · %d detail entries)", src,
                 spec["age_min"], spec["age_max"],
                 (spec.get("targeting_automation") or {}).get("advantage_audience"),
                 _richness({"flexible_spec": spec.get("flexible_spec", [])}))

        units, captions = [], {}
        for ad in ads:
            copy = ad["copy"][market]
            content_id = ad["content_id"] if market == "sg" else f"{market}-{ad['id']}"
            unit = make_unit(ad, assets_root, content_id)
            units.append(unit)
            captions[content_id] = {
                "caption": assemble(copy, blocks), "headline": copy["headline"],
                "description": copy.get("description", ""),
                "carousel_card_texts": copy.get("cards") or [],
            }
            log.info("   · %-13s %-2d asset(s)  %s", ad["kind"], len(unit.assets), content_id)

        media.sync_media(g, s, units, dry_run=False)
        try:
            ent = build(g, s, units=units, captions=captions, dry_run=False,
                        label=label, state_key=f"{grp['state_key']}_{market}",
                        adset_name=grp["adset_name"][market], targeting_override=spec)
        except GraphError as exc:
            log.error("!! build failed for %s: %s", label, exc)
            summary.append(f"  ✗ FAIL {label}: {exc}")
            continue

        n = len(ent.get("ad_ids") or [])
        total_ads += n
        summary.append(f"  {label:16} campaign={ent['campaign_id']} adset={ent['adset_id']} ads={n}")
        log.info("   ✓ campaign %s · adset %s · %d ad(s)", ent["campaign_id"], ent["adset_id"], n)

    log.info("═" * 88)
    for line in summary:
        log.info(line)
    final_summary(
        log, f"[{market}] batch built PAUSED: {total_ads} ads across {len(summary)} CBO campaigns "
             f"(RM{mk['daily_myr']}/day each). Review in Ads Manager, then activate selectively.")


if __name__ == "__main__":
    main()
