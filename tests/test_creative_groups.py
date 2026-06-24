from adbot.creative_groups import (CAROUSEL, SINGLE_IMAGE, VIDEO, Unit,
                                   build_units, select_ten, slugify, uniquify_ids)

FOLDER_MIME = "application/vnd.google-apps.folder"


def folder(fid, name, children):
    return {"id": fid, "name": name, "mimeType": FOLDER_MIME, "children": children}


def file(fid, name, mime):
    return {"id": fid, "name": name, "mimeType": mime}


def test_uniquify_ids_keeps_cjk_collisions():
    # Two distinct CJK-named images both slugify to "asset" -> must survive as asset / asset_2
    units = [Unit("asset", SINGLE_IMAGE), Unit("asset", SINGLE_IMAGE), Unit("carousel_1", CAROUSEL)]
    uniquify_ids(units)
    assert [u.content_id for u in units] == ["asset", "asset_2", "carousel_1"]
    assert len(select_ten(units, 10)) == 3  # none dropped


def test_slugify_drops_extension_and_normalizes():
    assert slugify("Promo Video 01.MP4") == "promo_video_01"


def test_slugify_preserves_cjk_and_hyphens():
    # CJK filenames used to collapse to 'asset', breaking Notion content-id matching for
    # non-ASCII batches. Keep CJK characters and hyphens; only the extension is stripped.
    assert slugify("单图-睡眠作息-图文繁.png") == "单图-睡眠作息-图文繁"
    assert slugify("单图-长得慢-繁.png") == "单图-长得慢-繁"
    assert slugify("简体.png") == "简体"
    # ASCII behavior unchanged: lower-case, hyphen kept (was treated as separator before too,
    # but now we preserve it). Verify the operator-facing slugs from the live batches still hold.
    assert slugify("sgmy_h1.mp4") == "sgmy_h1"
    assert slugify("Sgmy_H1.mp4") == "sgmy_h1"


def test_top_level_video_and_image_become_units():
    tree = folder("root", "root", [
        file("v1", "promo.mp4", "video/mp4"),
        file("i1", "single.jpg", "image/jpeg"),
    ])
    units = build_units(tree)
    assert sorted(u.kind for u in units) == [SINGLE_IMAGE, VIDEO]


def test_carousel_subfolder_groups_images_in_order():
    tree = folder("root", "root", [
        folder("c1", "Lesson Carousel", [
            file("b", "2.jpg", "image/jpeg"),
            file("a", "1.jpg", "image/jpeg"),
        ]),
    ])
    units = build_units(tree, marker="carousel")
    assert len(units) == 1 and units[0].kind == CAROUSEL
    assert [a.name for a in units[0].assets] == ["1.jpg", "2.jpg"]  # sorted by name


def test_script_sidecar_attaches_to_video():
    tree = folder("root", "root", [
        file("v1", "promo.mp4", "video/mp4"),
        file("t1", "promo.txt", "text/plain"),
    ])
    video = next(u for u in build_units(tree) if u.kind == VIDEO)
    assert video.assets[0].script_file_id == "t1"


def test_non_carousel_subfolder_is_walked_recursively():
    tree = folder("root", "root", [
        folder("sub", "extra clips", [file("v2", "deep.mp4", "video/mp4")]),
    ])
    units = build_units(tree)
    assert len(units) == 1 and units[0].kind == VIDEO


def test_select_ten_dedupes_and_caps():
    units = [Unit(f"c{i}", VIDEO) for i in range(12)] + [Unit("c0", VIDEO)]
    picked = select_ten(units, n=10)
    assert len(picked) == 10
    assert len({u.content_id for u in picked}) == 10
