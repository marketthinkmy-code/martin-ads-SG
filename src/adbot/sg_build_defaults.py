"""Targeting defaults for every new SG build (operator 22 Oct 「要」).

After the 10/20 老片重开 3 build the operator changed every ad set by hand to automatic
placements (Advantage+ placements) and added "frequently in" to the location types. New builds
start that way: copy the template's audience, then pass it through apply_sg_build_defaults().
"""
from __future__ import annotations

import copy
from typing import Any, Dict

PLACEMENT_KEYS = ("publisher_platforms", "facebook_positions", "instagram_positions",
                  "audience_network_positions", "messenger_positions", "threads_positions",
                  "device_platforms")
SG_LOCATION_TYPES = ["home", "frequently_in", "recent"]


def apply_sg_build_defaults(targeting: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of targeting with no placement fields (= automatic placements) and SG location
    types home + frequently in + recent. Audience fields are left as they are."""
    t = copy.deepcopy(targeting or {})
    for k in PLACEMENT_KEYS:
        t.pop(k, None)
    geo = t.setdefault("geo_locations", {})
    geo.setdefault("countries", ["SG"])
    geo["location_types"] = list(SG_LOCATION_TYPES)
    return t
