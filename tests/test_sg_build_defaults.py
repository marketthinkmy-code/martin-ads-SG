from adbot.sg_build_defaults import SG_LOCATION_TYPES, apply_sg_build_defaults


def test_placements_removed_and_location_types_set():
    tpl = {"age_min": 25, "geo_locations": {"countries": ["SG"], "location_types": ["home", "recent"]},
           "publisher_platforms": ["facebook", "instagram"], "facebook_positions": ["feed", "video_feeds"],
           "instagram_positions": ["stream"], "device_platforms": ["mobile", "desktop"],
           "flexible_spec": [{"interests": [{"id": "1"}]}]}
    t = apply_sg_build_defaults(tpl)
    for k in ("publisher_platforms", "facebook_positions", "instagram_positions", "device_platforms"):
        assert k not in t
    assert t["geo_locations"] == {"countries": ["SG"], "location_types": SG_LOCATION_TYPES}
    assert t["flexible_spec"] == tpl["flexible_spec"] and t["age_min"] == 25
    assert tpl["publisher_platforms"] == ["facebook", "instagram"]  # template untouched


def test_missing_geo_gets_sg():
    assert apply_sg_build_defaults({})["geo_locations"] == {"countries": ["SG"], "location_types": SG_LOCATION_TYPES}
