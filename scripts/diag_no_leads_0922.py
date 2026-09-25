"""Diagnose today's zero SG leads (read-only). Operator: "為什麼今天 sg 的都沒有 leads？？"

Three layers, worst-case first:
    ① Daily funnel compare (9/19 → today): spend · link clicks · CPC · leads · click→lead
      rate. Clicks flowing but zero leads = landing page / pixel problem (urgent, money
      burning); clicks cratered too = delivery-side (learning reset from today's budget
      changes, reviews).
    ② Landing page reachability right now: HTTP status, latency, size, form marker.
    ③ Pixel stats (best-effort): is CompleteRegistration firing at all these days —
      the pixel is shared with MY, so pixel-alive + SG-zero isolates the SG page/flow.
    Plus today's per-ad state: spend, clicks, effective_status (post-scale reviews?).
"""
from __future__ import annotations

import datetime as dt
import time as _time
from typing import Dict

import requests

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings


def links(actions) -> float:
    for a in actions or []:
        if a.get("action_type") == "link_click":
            try:
                return float(a.get("value") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = today - dt.timedelta(days=3)

    log.info("═" * 100)
    log.info("① 逐日漏斗对比（%s → %s · Meta 口径）", since, today)
    rows = g._get_all(f"{acct}/insights", {
        "level": "account", "fields": "spend,actions", "time_increment": 1,
        "time_range": f'{{"since":"{since}","until":"{today}"}}', "limit": 100})
    for r in rows:
        sp = float(r.get("spend") or 0)
        lc = links(r.get("actions"))
        ld = extract_results(r.get("actions"), token)
        cpc = f"RM{sp / lc:.2f}" if lc else "—"
        rate = f"{ld / lc * 100:.1f}%" if lc else "—"
        log.info("  %s  花 RM%-8.2f 链接点击 %-4d CPC %-8s leads %-3d 点击→lead %s",
                 r.get("date_start"), sp, int(lc), cpc, int(ld), rate)

    log.info("═" * 100)
    log.info("② 今天 per-ad（花费/点击/lead/状态）")
    ad_rows = g._get_all(f"{acct}/insights", {
        "level": "ad", "fields": "ad_id,ad_name,spend,actions",
        "time_range": f'{{"since":"{today}","until":"{today}"}}', "limit": 500})
    ids = [r.get("ad_id") for r in ad_rows if float(r.get("spend") or 0) > 0]
    effs: Dict[str, str] = {}
    for aid in ids:
        try:
            effs[aid] = g.get_object(aid, "effective_status").get("effective_status")
        except Exception:  # noqa: BLE001
            effs[aid] = "?"
    for r in sorted(ad_rows, key=lambda x: -float(x.get("spend") or 0)):
        sp = float(r.get("spend") or 0)
        if sp <= 0:
            continue
        log.info("  %-38s 花 RM%-7.2f 点击 %-3d lead %-2d eff %s",
                 (r.get("ad_name") or "?")[:38], sp, int(links(r.get("actions"))),
                 int(extract_results(r.get("actions"), token)), effs.get(r.get("ad_id")))

    log.info("═" * 100)
    url = s.meta.lead_destination.link_url
    log.info("③ landing page 现在的状态: %s", url)
    try:
        t0 = _time.time()
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        ms = ( _time.time() - t0) * 1000
        body = resp.text or ""
        marker = any(x in body for x in ("报名", "報名", "register", "form"))
        log.info("  HTTP %s · %.0f ms · %d bytes · 表单标记 %s",
                 resp.status_code, ms, len(body), "✓ 有" if marker else "✗ 没找到")
    except Exception as exc:  # noqa: BLE001
        log.error("  ✗ 打不开: %s", exc)

    log.info("═" * 100)
    log.info("④ pixel 侧（best-effort · pixel 与 MY 共用，pixel 活着但 SG 0 = SG 页面/流程问题）")
    try:
        po = s.meta.promoted_object or {}
        pix = po.get("pixel_id")
        start = int(_time.mktime((dt.datetime.utcnow() - dt.timedelta(days=3)).timetuple()))
        st = g._request("GET", f"{pix}/stats",
                        params={"aggregation": "event", "start_time": start})
        for row in (st.get("data") or [])[:8]:
            log.info("  %s", str(row)[:180])
    except Exception as exc:  # noqa: BLE001
        log.info("  pixel stats 读不到（%s）— 用 ①③ 判断即可", str(exc)[:120])

    final_summary(log, "Zero-lead diagnosis printed: funnel compare, per-ad state, "
                       "landing page health, pixel stats. Read-only.")


if __name__ == "__main__":
    main()
