"""Add one ad to the SG Test-ABO ad set from a Drive file + inline caption/headline.

One-off / iterable: the target ad set is `state/entities_test_abo.json`. Each
new creative appends itself to `ad_ids` + `built_content_ids`, and the script
is idempotent — a re-run whose content_id is already in `built_content_ids`
becomes a no-op.

To add a new ad: edit the ADS list at the bottom (drive_file_id + caption +
headline + optional content_id), commit, dispatch. The list is a queue — every
entry that hasn't been built yet gets built; already-built ones are skipped.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict, List, Optional

from adbot import state
from adbot.build_1_1_10 import creative_spec
from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.creative_groups import SINGLE_IMAGE, VIDEO, Asset, Unit, slugify
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_KEY = "entities_test_abo"


def _drive_meta(drive: DriveClient, file_id: str) -> Dict:
    """Fetch a single Drive file's metadata (name + mimeType + size)."""
    return drive._svc.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size",
        supportsAllDrives=True,
    ).execute()


def _build_unit(drive: DriveClient, file_id: str, content_id: Optional[str]) -> Unit:
    """Fetch metadata, pick VIDEO / SINGLE_IMAGE, return a synthesised Unit."""
    meta = _drive_meta(drive, file_id)
    mime = meta.get("mimeType") or ""
    if mime.startswith("video/"):
        kind = VIDEO
    elif mime.startswith("image/"):
        kind = SINGLE_IMAGE
    else:
        raise SystemExit(f"unsupported mime '{mime}' for file {file_id} ({meta.get('name')})")
    cid = content_id or slugify(meta.get("name") or file_id)
    asset = Asset(file_id=file_id, name=meta.get("name") or file_id, mime=mime)
    return Unit(content_id=cid, kind=kind, assets=[asset])


def _upload_asset(graph, drive: DriveClient, account_path: str, unit: Unit, tmp: Path) -> None:
    """Download the single asset from Drive and upload to Meta; stash meta_id on the Asset."""
    asset = unit.assets[0]
    ext = Path(asset.name).suffix or (".mp4" if unit.kind == VIDEO else ".jpg")
    local = tmp / f"{unit.content_id}{ext}"
    drive.download_file(asset.file_id, local)
    asset.local_path = str(local)
    if unit.kind == VIDEO:
        asset.meta_id = graph.upload_video(
            account_path, str(local), name=unit.content_id,
            poll_seconds=3, poll_timeout=180)
    else:
        asset.meta_id = graph.upload_image(account_path, str(local))


def _add_one(graph, drive: DriveClient, settings, spec: Dict, st: Dict) -> Optional[str]:
    """Build one ad end-to-end. Returns new ad_id or None if skipped (already built)."""
    log = get_logger()
    file_id = spec["drive_file_id"]
    content_id = spec.get("content_id") or slugify(_drive_meta(drive, file_id).get("name") or file_id)
    if content_id in set(st.get("built_content_ids") or []):
        log.info("  Skipping %s (already built)", content_id)
        return None

    unit = _build_unit(drive, file_id, content_id)
    with io.StringIO() as _:  # placeholder to keep the block explicit
        pass
    tmp = Path("/tmp/adbot_add_ad")
    tmp.mkdir(parents=True, exist_ok=True)
    _upload_asset(graph, drive, settings.meta.account_path, unit, tmp)
    log.info("  Uploaded %s -> meta_id %s", unit.content_id, unit.assets[0].meta_id)

    caption = {"caption": spec["caption"], "headline": spec["headline"]}
    thumb = graph.get_video_thumbnail(unit.assets[0].meta_id) if unit.kind == VIDEO else None
    creative_payload = creative_spec(settings, unit, caption, thumbnail_url=thumb)
    creative_id = graph.create_adcreative(settings.meta.account_path, **creative_payload)["id"]

    # Ad name follows the batch-build convention (Type：headline).
    label = "Video" if unit.kind == VIDEO else "Single Image"
    ad_name = spec.get("ad_name") or f"{label}：{spec['headline']}"
    ad = graph.create_ad(
        settings.meta.account_path,
        name=ad_name,
        adset_id=st["adset_id"],
        creative={"creative_id": creative_id},
        status="PAUSED",
        conversion_domain=settings.meta.conversion_domain_bare or None,
    )
    ad_id = ad["id"]
    log.info("  Created ad %s (%s, creative %s) name=%r", ad_id, unit.kind, creative_id, ad_name)
    return ad_id


def add_ads(specs: List[Dict]) -> None:
    log = get_logger()
    settings = load_settings()   # ADBOT_CONFIG should point at config/test-abo.yaml
    graph = graph_client(settings)
    drive = DriveClient(settings.secrets.google_sa_json)

    st = state.load(STATE_KEY)
    if not st.get("adset_id"):
        raise SystemExit(f"state/{STATE_KEY}.json has no adset_id — build the skeleton first")
    ad_ids: List[str] = list(st.get("ad_ids") or [])
    built = set(st.get("built_content_ids") or [])

    for spec in specs:
        new_id = _add_one(graph, drive, settings, spec, st)
        if new_id:
            ad_ids.append(new_id)
            built.add(spec.get("content_id") or
                      slugify(_drive_meta(drive, spec["drive_file_id"]).get("name") or ""))
            state.save(STATE_KEY, {
                **st,
                "ad_ids": ad_ids,
                "built_content_ids": sorted(built),
            })
            st = state.load(STATE_KEY)   # reload to keep it consistent

    final_summary(
        log,
        f"add_ad_test_abo: {len(ad_ids)} ad(s) total under Test-ABO adset "
        f"{st['adset_id']} (all PAUSED — activate in Ads Manager after review).")


# ─── the queue: add new ad specs to this list, commit, dispatch ─────────────
ADS: List[Dict] = [
    {
        "drive_file_id": "11FCTfkzh7CuP74_GHhqmxArWeE2hlnki",
        "content_id": "sg-test-孩子矮一个头-免费分享会",
        "headline": "🔴 孩子矮一个头，最痛的是他自己｜免费线上分享会",
        "caption": (
            "😔 孩子排队永远站最前面，拍照永远被安排在最旁边——\n"
            "你以为他不在意，其实他只是不敢跟你说。\n"
            "\n"
            "孩子比同学矮一个头，\n"
            "真正痛苦的，不是爸妈，是孩子自己。\n"
            "\n"
            "💔 同学一句玩笑话，\n"
            "他表面笑笑，心里其实很在意。\n"
            "\n"
            "很多爸妈会安慰自己：\n"
            "🗣️「没关系啦，之后还会长。」\n"
            "🗣️「我们也不高，可能就是遗传。」\n"
            "\n"
            "然后一急起来，就开始乱补——\n"
            "🍼 奶粉、钙片、增高保健品全上，\n"
            "还逼孩子跳绳、打球、早睡。\n"
            "\n"
            "补了一堆，孩子没长高，\n"
            "😤 反而开始抗拒你：\n"
            "一叫他喝奶，他嫌你烦；\n"
            "一提到身高，他直接不想听。\n"
            "\n"
            "马丁药师说了一句让很多家长沉默的话：\n"
            "👉「孩子长不高，不一定是缺钙。不是你不努力，是你还没找出孩子卡在哪里。」\n"
            "\n"
            "😴 有的孩子是睡眠乱了\n"
            "🥣 有的是吃很多但吸收不好\n"
            "🏃 有的是运动方向做错\n"
            "⏳ 有的是青春期窗口已经在变窄\n"
            "✅ 先找出卡点，再决定怎么追高。\n"
            "\n"
            "马丁药师（台湾执照药师 · 中西医结合背景）\n"
            "将在限时免费线上分享会里，带你看懂：\n"
            "\n"
            "📍 孩子长不高，通常卡在哪 5 个关卡\n"
            "📍 怎样判断孩子的青春期窗口还剩多少\n"
            "📍 如何用最健康的方式调理体质，帮孩子每年健康长高 6–8cm\n"
            "\n"
            "⏰ 名额有限，坐满即止。\n"
            "👇 点击下方链接，立即免费报名\n"
            "别再让孩子一个人扛。"
        ),
    },
]


if __name__ == "__main__":
    add_ads(ADS)
