"""Read-only (13 Nov): the 5 MY existing posts the operator wants to reuse on SG老户.

Operator 13 Nov: 「建广告的话，直接用 existing post id，id 我等 MY 那边给你」. Before any build:
  1. each post's text, permalink, call-to-action link (must be the SG registration page, else SG
     registrations land in MY's funnel) and attached link;
  2. every ad on MY act_1011719073600566 (read only) / HK / SG老户 whose creative uses that post,
     with lifetime spend, impressions, link clicks, registrations (Meta) and CPL.
ADBOT_POST_IDS = comma-separated page_post ids. No writes.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("MY", "act_1011719073600566"), ("HK", "act_1179668409969241"), ("SG老户", "act_1024930575770087")]


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    posts = [x.strip() for x in os.environ.get("ADBOT_POST_IDS", "").split(",") if x.strip()]
    for pid in posts:
        log.info("════ post %s", pid)
        try:
            p = g.get_object(pid, "message,permalink_url,created_time,is_published,call_to_action,"
                                  "attachments{media_type,url,unshimmed_url,title,target}")
        except Exception as exc:  # noqa: BLE001
            log.info("  读不到 post：%s", str(exc)[:300])
            continue
        log.info("  建立 %s · 已发布 %s · %s", p.get("created_time"), p.get("is_published"), p.get("permalink_url"))
        log.info("  CTA：%s", json.dumps(p.get("call_to_action"), ensure_ascii=False))
        for a in (p.get("attachments") or {}).get("data", []):
            log.info("  附件：%s · %s · %s", a.get("media_type"), a.get("unshimmed_url") or a.get("url"), a.get("title"))
        log.info("  文案：\n%s", p.get("message") or "（没有文案）")
    found = defaultdict(list)
    for label, acct in ACCTS:
        try:
            ads = g._get_all(f"{acct}/ads", {"limit": 200, "fields": "id,name,effective_status,created_time,"
                             "campaign{name},adset{name},creative{effective_object_story_id,object_story_id,url_tags}",
                             "filtering": json.dumps([{"field": "ad.created_time", "operator": "GREATER_THAN",
                                                       "value": 1761926400}])})  # 2025-11-01, generous
        except Exception as exc:  # noqa: BLE001
            log.info("%s 读广告失败：%s", label, str(exc)[:300])
            continue
        log.info("%s：读到 %d 支广告", label, len(ads))
        for ad in ads:
            cr = ad.get("creative") or {}
            post = cr.get("effective_object_story_id") or cr.get("object_story_id")
            if post in posts:
                found[post].append((label, ad))
    for pid in posts:
        log.info("════ 用 post %s 的广告：%d 支", pid, len(found[pid]))
        for label, ad in found[pid]:
            try:
                ins = g._get_all(f"{ad['id']}/insights", {"date_preset": "maximum", "fields":
                                 "spend,impressions,inline_link_clicks,actions,date_start,date_stop"})
            except Exception as exc:  # noqa: BLE001
                log.info("  %s %s insights 失败 %s", label, ad["id"], str(exc)[:200])
                continue
            r = ins[0] if ins else {}
            sp = float(r.get("spend") or 0)
            reg = extract_results(r.get("actions"), tok)
            log.info("  %s · %s · ad %s · %s · campaign %s · ad set %s · %s~%s · 花 %.2f · 曝光 %s · 点击 %s · 报名 %d · CPL %s · url_tags %s",
                     label, ad.get("name"), ad["id"], ad.get("effective_status"),
                     (ad.get("campaign") or {}).get("name"), (ad.get("adset") or {}).get("name"),
                     r.get("date_start"), r.get("date_stop"), sp, r.get("impressions"), r.get("inline_link_clicks"),
                     reg, f"{sp / reg:.2f}" if reg else "—", (ad.get("creative") or {}).get("url_tags"))
    final_summary(log, f"posts read: {len(posts)} · read-only")


if __name__ == "__main__":
    main()
