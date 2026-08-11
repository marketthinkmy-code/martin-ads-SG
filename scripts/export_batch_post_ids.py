"""Export the SG creative batch's page-post ids so the MY account can reuse them.

Ads built from an inline object_story_spec get an unpublished ("dark") page post behind them.
Its id lives on the creative as effective_object_story_id, shaped "<page_id>_<post_id>". Because
the post belongs to the PAGE — and MY and SG run on the SAME page (341825319024143 in both
configs) — the MY ad account can point a creative at it with {"object_story_id": ...} instead of
re-uploading 52 assets.

Prints a JSON block the MY build reads directly, and writes state/sg_batch_post_ids.json.

Reuse means the two markets SHARE one post: likes, comments and shares pool together (the point
of doing it), but so do the comments — an MY parent's question shows up under the SG ad too.
Both markets bill in MYR and share the landing page, so that is survivable here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

CAMPAIGNS = [
    ("a_knowledge", "知识科普 | A", "120257496408700093"),
    ("b_myths",     "迷思打破 | B", "120257496414280093"),
    ("c_proof",     "见证证明 | C", "120257496423420093"),
    ("d_emotion",   "焦虑情感 | D", "120257496426410093"),
    ("e_lowkey",    "低期待值 | E", "120257496431280093"),
    ("f_backup",    "备用 | F",     "120257496434870093"),
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    out: Dict[str, Any] = {"page_id": s.meta.page_id, "groups": {}}
    total = missing = 0

    for key, label, campaign_id in CAMPAIGNS:
        ads = g._get_all(f"{campaign_id}/ads", {
            "fields": "id,name,status,creative{id,effective_object_story_id,object_story_id}",
            "limit": 200})
        rows: List[Dict[str, str]] = []
        log.info("═" * 92)
        log.info("── %s  (campaign %s · %d ads)", label, campaign_id, len(ads))
        for a in ads:
            creative = a.get("creative") or {}
            post_id = creative.get("effective_object_story_id") or creative.get("object_story_id")
            total += 1
            if not post_id:
                missing += 1
                log.warning("   ‼ %s %r — no post id on creative %s",
                            a["id"], (a.get("name") or "")[:44], creative.get("id"))
                continue
            rows.append({"ad_id": a["id"], "name": a.get("name") or "",
                         "creative_id": creative.get("id") or "", "post_id": post_id})
            log.info("   %-46s %s", (a.get("name") or "")[:46], post_id)
        out["groups"][key] = {"label": label, "sg_campaign_id": campaign_id, "ads": rows}

    path = Path("state") / "sg_batch_post_ids.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    log.info("═" * 92)
    log.info("JSON (paste into the MY build):")
    for line in json.dumps(out, ensure_ascii=False, indent=2).splitlines():
        log.info("  %s", line)
    final_summary(
        log, f"Exported {total - missing}/{total} post ids across {len(CAMPAIGNS)} campaigns → "
             f"{path}. MY can reuse these via creative object_story_id (same page id "
             f"{s.meta.page_id} in both configs), so no asset re-upload is needed."
             + (f" ‼ {missing} ad(s) had no post id — those need rebuilding from assets."
                if missing else ""))


if __name__ == "__main__":
    main()
