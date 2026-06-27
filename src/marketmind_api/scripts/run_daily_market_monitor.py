from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from marketmind_api.runtime import ensure_runtime_paths

ensure_runtime_paths()

from marketmind_api.core.config import settings
from marketmind_api.services.daily_market_monitor import DailyMarketMonitorService


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and push the daily market monitor brief.")
    parser.add_argument("--daemon", action="store_true", help="Keep the process alive and run every day at the configured time.")
    parser.add_argument("--run-at", default=settings.market_monitor_run_at, help="Daily run time(s) in HH:MM,HH:MM.")
    parser.add_argument("--print-only", action="store_true", help="Render the brief locally without sending to Feishu.")
    parser.add_argument("--json", action="store_true", help="Print the brief as JSON instead of formatted text.")
    args = parser.parse_args()

    service = DailyMarketMonitorService()
    if args.daemon:
        _run_daemon(service, args.run_at, args.print_only, args.json)
        return

    _run_once(service, args.print_only, args.json)


def _run_once(service: DailyMarketMonitorService, print_only: bool, json_output: bool) -> None:
    report = service.build_report()
    if json_output:
        print(json.dumps(_report_to_dict(report), ensure_ascii=False, indent=2, default=str))
    else:
        print(report.render_text())

    if print_only:
        return

    delivery = service.send_report(report)
    print(delivery.detail)
    if not delivery.sent:
        raise SystemExit(1)


def _run_daemon(service: DailyMarketMonitorService, run_at: str, print_only: bool, json_output: bool) -> None:
    run_times = _parse_run_at_list(run_at)
    last_run_key: str | None = None
    while True:
        target = _next_run_time(service.timezone, run_times)
        now = datetime.now(service.timezone)
        sleep_seconds = max(1, int((target - now).total_seconds()))
        print(f"[daily-monitor] next run at {target:%Y-%m-%d %H:%M:%S %Z}, sleeping {sleep_seconds}s")
        time.sleep(sleep_seconds)
        run_key = target.strftime("%Y-%m-%d %H:%M")
        if run_key == last_run_key:
            time.sleep(1)
            continue
        try:
            _run_once(service, print_only, json_output)
            last_run_key = run_key
        except Exception as exc:
            print(f"[daily-monitor] run failed: {exc}")
            time.sleep(300)


def _next_run_time(timezone, run_times: list[tuple[int, int]]) -> datetime:
    now = datetime.now(timezone)
    candidates: list[datetime] = []
    for hour, minute in run_times:
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        candidates.append(target)
    return min(candidates)


def _parse_run_at_list(value: str) -> list[tuple[int, int]]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise ValueError("MARKET_MONITOR_RUN_AT must contain at least one time")
    return [_parse_run_at(item) for item in parts]


def _parse_run_at(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except Exception as exc:
        raise ValueError(f"Invalid run time '{value}', expected HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid run time '{value}', expected HH:MM")
    return hour, minute


def _report_to_dict(report) -> dict[str, object]:
    return {
        "generated_at": report.generated_at.isoformat(),
        "btc_price": report.btc_price,
        "macro_score": report.macro_score,
        "btc_score": report.btc_score,
        "risk_appetite": report.risk_appetite,
        "btc_direction": report.btc_direction,
        "tradable": report.tradable,
        "text": report.render_text(),
    }


if __name__ == "__main__":
    main()
