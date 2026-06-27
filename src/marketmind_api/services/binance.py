from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from json import loads
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class BinanceMarketSpec:
    symbol: str
    timeframe: str


@dataclass(frozen=True)
class BinanceCandle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class BinanceMarketSnapshotPayload:
    symbol: str
    timeframe: str
    candle: BinanceCandle
    funding_rate: float | None
    open_interest: float | None
    long_short_ratio: float | None
    source: str = "binance"


@dataclass(frozen=True)
class BinanceTicker24hPayload:
    symbol: str
    last_price: float
    price_change_percent: float
    high_price: float
    low_price: float
    volume: float
    quote_volume: float


@dataclass(frozen=True)
class BinanceKlinePage:
    candles: list[BinanceCandle]
    has_more: bool


class BinanceClient:
    def __init__(
        self,
        rest_base_url: str,
        ws_base_url: str,
        futures_ws_base_url: str | None = None,
    ) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_base_url = ws_base_url.rstrip("/")
        self.futures_ws_base_url = (futures_ws_base_url or ws_base_url).rstrip("/")

    def supported_markets(self) -> list[BinanceMarketSpec]:
        return [
            BinanceMarketSpec(symbol="BTCUSDT", timeframe="1m"),
            BinanceMarketSpec(symbol="BTCUSDT", timeframe="5m"),
            BinanceMarketSpec(symbol="BTCUSDT", timeframe="15m"),
            BinanceMarketSpec(symbol="BTCUSDT", timeframe="1h"),
            BinanceMarketSpec(symbol="BTCUSDT", timeframe="4h"),
            BinanceMarketSpec(symbol="BTCUSDT", timeframe="1d"),
            BinanceMarketSpec(symbol="ETHUSDT", timeframe="1m"),
            BinanceMarketSpec(symbol="ETHUSDT", timeframe="5m"),
            BinanceMarketSpec(symbol="ETHUSDT", timeframe="15m"),
            BinanceMarketSpec(symbol="ETHUSDT", timeframe="1h"),
            BinanceMarketSpec(symbol="ETHUSDT", timeframe="4h"),
            BinanceMarketSpec(symbol="ETHUSDT", timeframe="1d"),
            BinanceMarketSpec(symbol="SOLUSDT", timeframe="1m"),
            BinanceMarketSpec(symbol="SOLUSDT", timeframe="5m"),
            BinanceMarketSpec(symbol="SOLUSDT", timeframe="15m"),
            BinanceMarketSpec(symbol="SOLUSDT", timeframe="1h"),
            BinanceMarketSpec(symbol="SOLUSDT", timeframe="4h"),
            BinanceMarketSpec(symbol="SOLUSDT", timeframe="1d"),
        ]

    def fetch_latest_candle(self, symbol: str, timeframe: str, limit: int = 1) -> BinanceCandle:
        payload = self._get_json(
            "/api/v3/klines",
            {"symbol": symbol, "interval": timeframe, "limit": limit},
        )
        if not payload:
            raise ValueError(f"No kline data returned for {symbol} {timeframe}")
        row = payload[-1]
        return BinanceCandle(
            open_time=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )

    def fetch_latest_funding_rate(self, symbol: str) -> float | None:
        try:
            payload = self._get_json(
                "/fapi/v1/fundingRate",
                {"symbol": symbol, "limit": 1},
            )
        except (HTTPError, URLError, ValueError):
            return None
        if not payload:
            return None
        return float(payload[-1]["fundingRate"])

    def fetch_open_interest(self, symbol: str) -> float | None:
        try:
            payload = self._get_json("/fapi/v1/openInterest", {"symbol": symbol})
        except (HTTPError, URLError, ValueError):
            return None
        open_interest = payload.get("openInterest")
        return float(open_interest) if open_interest is not None else None

    def fetch_long_short_ratio(self, symbol: str) -> float | None:
        try:
            payload = self._get_json(
                "/futures/data/globalLongShortAccountRatio",
                {"symbol": symbol, "period": "1d", "limit": 1},
            )
        except (HTTPError, URLError, ValueError):
            return None
        if not payload:
            return None
        item = payload[-1]
        ratio_value = item.get("longShortRatio")
        return float(ratio_value) if ratio_value is not None else None

    def fetch_latest_snapshot(self, symbol: str, timeframe: str) -> BinanceMarketSnapshotPayload:
        candle = self.fetch_latest_candle(symbol, timeframe)
        return BinanceMarketSnapshotPayload(
            symbol=symbol,
            timeframe=timeframe,
            candle=candle,
            funding_rate=self.fetch_latest_funding_rate(symbol),
            open_interest=self.fetch_open_interest(symbol),
            long_short_ratio=self.fetch_long_short_ratio(symbol),
        )

    def fetch_24h_ticker(self, symbol: str) -> BinanceTicker24hPayload:
        payload = self._get_json("/api/v3/ticker/24hr", {"symbol": symbol})
        if not isinstance(payload, dict):
            raise ValueError(f"No ticker data returned for {symbol}")
        return BinanceTicker24hPayload(
            symbol=symbol,
            last_price=float(payload.get("lastPrice", 0.0)),
            price_change_percent=float(payload.get("priceChangePercent", 0.0)),
            high_price=float(payload.get("highPrice", 0.0)),
            low_price=float(payload.get("lowPrice", 0.0)),
            volume=float(payload.get("volume", 0.0)),
            quote_volume=float(payload.get("quoteVolume", 0.0)),
        )

    def fetch_klines(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 1000,
    ) -> BinanceKlinePage:
        params: dict[str, object] = {"symbol": symbol, "interval": timeframe, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)

        payload = self._get_json("/api/v3/klines", params)
        candles = [
            BinanceCandle(
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in payload
        ]
        has_more = len(candles) == limit
        return BinanceKlinePage(candles=candles, has_more=has_more)

    def _get_json(self, path: str, params: dict[str, object]) -> object:
        url = f"{self.rest_base_url}{path}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "MarketMind/0.1"})
        with urlopen(request, timeout=15) as response:
            return loads(response.read().decode("utf-8"))
