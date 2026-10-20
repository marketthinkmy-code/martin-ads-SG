"""What did the operator change on 老片重开 3? (read-only, 20 Oct; operator: 我弄好了你剛剛開的 campaign)

For every ad set / ad in state/entities_relaunch3_1020.json: current targeting vs the targeting the
build script sends (template + the same edits), budget, bid, optimisation, attribution, placements;
current creative id vs the one built, and the creative's fields if it was swapped. No writes.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

HW_TPL = "120250914933290093"
TPL = {"hw": HW_TPL, "lux": "120238644972660093"}
ADSET_F = ("name,daily_budget,bid_strategy,optimization_goal,billing_event,attribution_spec,promoted_object,"
           "start_time,end_time,targeting,updated_time")
AD_F = ("name,status,effective_status,creative{id,name,object_story_id,effective_object_story_id,url_tags,body,title,"
        "call_to_action_type},updated_time")


def built_targeting(g, key, excl):
    t = copy.deepcopy(g.get_object(TPL[key], "targeting").get("targeting") or {})
    t["excluded_custom_audiences"] = [{"id": x["id"]} for x in excl]
    if t.get("genders") in ([0], []):
        t.pop("genders", None)
    t.pop("custom_audiences", None)
    fbp = t.get("facebook_positions")
    if fbp and "video_feeds" in fbp:
        t["facebook_positions"] = [x for x in fbp if x != "video_feeds"]
    ig = t.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        t["instagram_positions"] = list(ig) + ["explore"]
    return t


def norm(v):
    if isinstance(v, list):
        return sorted(json.dumps(norm(x), sort_keys=True, ensure_ascii=False) for x in v)
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items() if k != "name"}
    return v


def main():
    log = get_logger()
    g = graph_client(load_settings())
    st = json.loads(Path("state/entities_relaunch3_1020.json").read_text())
    excl = (g.get_object(HW_TPL, "targeting").get("targeting") or {}).get("excluded_custom_audiences") or []
    want = {k: built_targeting(g, k, excl) for k in TPL}
    for slot, sid in st["adsets"].items():
        ck = slot.split(":")[0]
        a = g.get_object(sid, ADSET_F)
        cur, w = a.get("targeting") or {}, want[ck]
        log.info("═" * 100)
        log.info("▌ad set %s %r (%s) · RM%d · %s · %s · 改于 %s", sid, a.get("name"), slot,
                 int(a.get("daily_budget") or 0) // 100, a.get("optimization_goal"), a.get("bid_strategy"), a.get("updated_time"))
        log.info("  attribution %s · start %s · end %s", json.dumps(a.get("attribution_spec"), ensure_ascii=False),
                 a.get("start_time"), a.get("end_time"))
        diffs = 0
        for k in sorted(set(cur) | set(w)):
            if norm(cur.get(k)) != norm(w.get(k)):
                diffs += 1
                log.info("  定向不同 %-28s 我建的：%s", k, json.dumps(w.get(k), ensure_ascii=False)[:300])
                log.info("  %-36s 现在的：%s", "", json.dumps(cur.get(k), ensure_ascii=False)[:300])
        if not diffs:
            log.info("  定向：和我建的一样")
    for slot, aid in st["ads"].items():
        ad = g.get_object(aid, AD_F)
        cr = ad.get("creative") or {}
        same = cr.get("id") == st["creatives"][slot.split(":")[1]]
        log.info("▌ad %s %r (%s) · %s/%s · 改于 %s · creative %s %s", aid, ad.get("name"), slot, ad.get("status"),
                 ad.get("effective_status"), ad.get("updated_time"), cr.get("id"), "（没换）" if same else "（换过了）")
        if not same:
            log.info("    现在的 creative：%s", json.dumps(cr, ensure_ascii=False)[:600])
    final_summary(log, "diff 老片重开 3 · read-only")


if __name__ == "__main__":
    main()
