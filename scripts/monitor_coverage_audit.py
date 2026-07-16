"""Read-only coverage audit for the CPL+CPA monitor across the 3 accounts we want
it to cover (SG + MY + 加州/US).

For each account it prints: currency, active-campaign count, and — per active
campaign — how many ACTIVE ads are registration-optimized (i.e. IN monitor scope,
since the monitor only judges ads whose ad set optimizes for COMPLETE_REGISTRATION)
vs skipped (a different conversion event, therefore currently OUT of scope).

This answers "are all my active campaign/adset/ads actually covered?" and reveals
each account's currency + conversion event so the per-account monitor config can be
set correctly (RM thresholds are only valid for MYR accounts).
"""
from __future__ import annotations

from collections import defaultdict

from adbot.clients.graph import GraphClient
from adbot.settings import load_settings

WANT_EVENT = "COMPLETE_REGISTRATION"

ACCOUNTS = [
    ("SG",      "act_1024930575770087"),
    ("MY",      "act_1011719073600566"),
    ("加州/US", "act_1629566827721449"),
]


def main() -> None:
    s = load_settings()
    g = GraphClient(s.secrets.meta_token, "")

    for label, acct in ACCOUNTS:
        print("═" * 84)
        try:
            info = g.get_object(acct, "name,currency,account_status")
        except Exception as e:                       # noqa: BLE001
            print(f" {label}  {acct}  — cannot read account: {e}")
            continue
        print(f" {label}  ·  {acct}  ·  {info.get('name','?')}  ·  currency={info.get('currency','?')}")
        print("═" * 84)

        try:
            camps = g._get_all(f"{acct}/campaigns",
                               {"fields": "name,effective_status,objective", "limit": 300})
        except Exception as e:                       # noqa: BLE001
            print(f"   ! campaigns read failed: {e}")
            continue
        active = [c for c in camps if c.get("effective_status") == "ACTIVE"]
        print(f"   campaigns: {len(camps)} total · {len(active)} ACTIVE\n")

        tot_ads = monitored = skipped = 0
        event_hist: dict[str, int] = defaultdict(int)
        skipped_ex: list[tuple[str, str, str]] = []
        for c in sorted(active, key=lambda c: c.get("name", "")):
            try:
                ads = g._get_all(f"{c['id']}/ads",
                                 {"fields": "name,effective_status,adset{optimization_goal,promoted_object}",
                                  "limit": 200})
            except Exception as e:                   # noqa: BLE001
                print(f"   ! ads read failed for {c.get('name','')[:30]}: {e}")
                continue
            a_active = m = k = 0
            for ad in ads:
                if ad.get("effective_status") != "ACTIVE":
                    continue
                a_active += 1
                tot_ads += 1
                ev = ((ad.get("adset") or {}).get("promoted_object") or {}).get("custom_event_type") or "(none)"
                event_hist[ev] += 1
                if ev.upper() == WANT_EVENT:
                    m += 1
                    monitored += 1
                else:
                    k += 1
                    skipped += 1
                    if len(skipped_ex) < 12:
                        skipped_ex.append((c.get("name", "")[:34], ad.get("name", "")[:30], ev))
            if a_active:
                flag = "" if k == 0 else f"  ⚠ {k} NOT registration-optimized"
                print(f"   [{a_active:>3} active ad] {c.get('name','')[:52]:52} "
                      f"mon={m} skip={k}{flag}")

        print(f"\n   ── {label} totals: {tot_ads} active ads · "
              f"{monitored} IN monitor scope · {skipped} OUT (non-registration) ──")
        print(f"   active-ad conversion events: "
              f"{dict(sorted(event_hist.items(), key=lambda kv: -kv[1]))}")
        if skipped_ex:
            print(f"   examples OUT of scope (campaign · ad · event):")
            for cn, an, ev in skipped_ex:
                print(f"      · {cn}  |  {an}  |  {ev}")
        print()


if __name__ == "__main__":
    main()
