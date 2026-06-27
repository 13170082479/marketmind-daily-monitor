from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from marketmind_api.runtime import ensure_runtime_paths

ensure_runtime_paths()

from marketmind_api.services.daily_market_monitor import DailyMarketMonitorService


def main() -> None:
    service = DailyMarketMonitorService()
    report, delivery = service.run_once()
    print(report.render_text())
    print(delivery.detail)
    if not delivery.sent:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
