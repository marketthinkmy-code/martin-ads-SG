"""Build the singleimg-e 1-1-1 campaign: 1 campaign + 1 ad set + 1 ad (PAUSED).

Downloads the ad's source file from Drive, uploads to Meta (image_hash or
video_id), then hands a fully-populated Unit + captions dict to
adbot.build_1_1_10.build() — reusing the exact same code path (SG compliance,
state persistence, resumability) as the batch builds.

Idempotent: re-runs reuse the campaign_id / adset_id / ad_ids in
state/entities_singleimg_e.json and the media in state/media_cache.json, so
an accidental second dispatch is a full no-op.

Edit AD_SPEC below and dispatch again to build a fresh 1-1-1 with new
material (bump `state_key` in the config too, or the second ad won't build —
the state carries `built_content_ids`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from adbot import media
from adbot.build_1_1_10 import build
from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.creative_groups import SINGLE_IMAGE, VIDEO, Asset, Unit
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

# ─── the ad's spec — edit + re-dispatch for the next 1-1-1 test ──────────────
AD_SPEC: Dict[str, str] = {
    "drive_file_id": "11FCTfkzh7CuP74_GHhqmxArWeE2hlnki",
    "content_id":    "sg-test-孩子矮一个头-免费分享会",
    "headline":      "🔴 孩子矮一个头，最痛的是他自己｜免费线上分享会",
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
}


def main() -> None:
    log = get_logger()
    settings = load_settings()
    graph = graph_client(settings)
    drive = DriveClient(settings.secrets.google_sa_json)

    # 1. Fetch Drive metadata, pick VIDEO vs SINGLE_IMAGE by mime.
    meta = drive._svc.files().get(
        fileId=AD_SPEC["drive_file_id"],
        fields="id,name,mimeType,size",
        supportsAllDrives=True,
    ).execute()
    mime = meta.get("mimeType") or ""
    if mime.startswith("video/"):
        kind = VIDEO
    elif mime.startswith("image/"):
        kind = SINGLE_IMAGE
    else:
        raise SystemExit(f"unsupported mime '{mime}' for file {meta.get('name')!r}")

    # 2. Download the source into a local tmp path — media.sync_media reads
    #    from asset.local_path when uploading.
    tmp = Path("/tmp/adbot_singleimg_e")
    tmp.mkdir(parents=True, exist_ok=True)
    ext = Path(meta.get("name") or "").suffix or (".mp4" if kind == VIDEO else ".jpg")
    local = tmp / f"{AD_SPEC['content_id']}{ext}"
    drive.download_file(AD_SPEC["drive_file_id"], local)
    log.info("Downloaded %s (%s bytes) -> %s", meta.get("name"), meta.get("size"), local)

    # 3. Synthesise a fully-populated Unit and let media.sync_media upload it
    #    (or reuse the cached meta_id from an earlier run).
    asset = Asset(
        file_id=AD_SPEC["drive_file_id"],
        name=meta.get("name") or AD_SPEC["content_id"],
        mime=mime,
        local_path=str(local),
    )
    unit = Unit(content_id=AD_SPEC["content_id"], kind=kind, assets=[asset])
    media.sync_media(graph, settings, [unit], dry_run=False)

    # 4. Hand off to build_1_1_10 — creates campaign + adset + 1 ad (PAUSED)
    #    with SG compliance, state persistence, resumability.
    captions = {
        AD_SPEC["content_id"]: {"caption": AD_SPEC["caption"], "headline": AD_SPEC["headline"]},
    }
    entities = build(
        graph, settings,
        units=[unit],
        captions=captions,
        dry_run=False,
        label=settings.meta.build.label,
        state_key=settings.meta.build.state_key,
    )
    log.info("  campaign_id: %s", entities["campaign_id"])
    log.info("  adset_id:    %s", entities["adset_id"])
    log.info("  ad_ids:      %s", entities["ad_ids"])
    final_summary(
        log,
        f"singleimg-e 1-1-1 built (PAUSED). Campaign {entities['campaign_id']}, "
        f"ad set {entities['adset_id']}, {len(entities['ad_ids'])} ad(s). "
        "Set placements (FB Feed/Reels + IG Feed) + activate in Ads Manager.")


if __name__ == "__main__":
    main()
