from __future__ import annotations

import base64
import os
import csv
import hashlib
import hmac
import json
import math
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from marketmind_api.core.config import settings
from marketmind_api.services.binance import BinanceClient


_YAHOO_DXY_SYMBOLS = ["DX-Y.NYB"]
_YAHOO_NQ_SYMBOLS = ["NQ=F"]
_YAHOO_GOLD_SYMBOLS = ["XAUUSD=X", "GC=F"]
_FRED_10Y_SERIES = "DGS10"
_FRED_2Y_SERIES = "DGS2"
_TREASURY_DAILY_YIELD_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"
_FARSIDE_BTC_ETF_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"


@dataclass(frozen=True)
class QuoteSnapshot:
    label: str
    symbol: str
    price: float | None
    previous_close: float | None
    change: float | None
    change_pct: float | None
    as_of: datetime | None
    source: str
    unit: str = "price"


@dataclass(frozen=True)
class EtfFlowSnapshot:
    flow_date: date | None
    total: float | None
    holdings: dict[str, float | None]
    source: str
    recent_total: float | None = None


@dataclass(frozen=True)
class TimeframeStructure:
    timeframe: str
    last_close: float | None
    ema20: float | None
    ema50: float | None
    ema100: float | None
    above_ema20: bool | None
    above_ema50: bool | None
    above_ema100: bool | None
    support: float | None
    resistance: float | None
    volume_ratio: float | None
    sweep: str | None
    breakout: str | None
    regime: str
    summary: str


@dataclass(frozen=True)
class DailyMarketBrief:
    generated_at: datetime
    btc_price: float | None
    dxy: QuoteSnapshot | None
    us10y: QuoteSnapshot | None
    us2y: QuoteSnapshot | None
    nq: QuoteSnapshot | None
    gold: QuoteSnapshot | None
    etf_flow: EtfFlowSnapshot | None
    structures: list[TimeframeStructure]
    macro_score: int
    btc_score: int
    risk_appetite: str
    btc_direction: str
    tradable: str
    reminder_lines: list[str] = field(default_factory=list)

    def render_text(self) -> str:
        lines: list[str] = []
        lines.append("【每日市场简报】")
        lines.append("")
        lines.append(f"时间：{self.generated_at:%Y-%m-%d %H:%M:%S %Z}")
        lines.append(f"BTC 当前价格：{_format_price(self.btc_price, decimals=2)}")
        lines.append("")
        lines.append("一、宏观环境")
        lines.append(f"DXY：{_render_quote(self.dxy)}")
        lines.append(f"美债收益率：{_render_yield_pair(self.us10y, self.us2y)}")
        lines.append(f"纳指期货：{_render_quote(self.nq)}")
        lines.append(f"黄金：{_render_gold(self.gold, self.dxy)}")
        lines.append("")
        lines.append("二、机构资金")
        lines.append(f"BTC ETF 净流入/流出：{_render_etf_total(self.etf_flow)}")
        lines.append(f"主要 ETF 变化：{_render_etf_holdings(self.etf_flow)}")
        lines.append(f"机构判断：{_render_etf_judgement(self.etf_flow)}")
        lines.append("")
        lines.append("三、BTC 技术结构")
        for structure in self.structures:
            lines.append(f"{structure.timeframe}：{structure.summary}")
        lines.append("")
        lines.append("四、今日市场判断")
        lines.append(f"风险偏好：{self.risk_appetite}")
        lines.append(f"BTC方向：{self.btc_direction}")
        lines.append(f"是否适合交易：{self.tradable}")
        lines.append("")
        lines.append("五、交易提醒")
        lines.extend([f"- {line}" for line in self.reminder_lines])
        return "\n".join(lines)


@dataclass(frozen=True)
class DeliveryResult:
    sent: bool
    channel: str
    detail: str


def buildMarketBriefCard(report: DailyMarketBrief) -> dict[str, Any]:
    summary_color = _card_template_for_report(report)
    summary_emoji = _summary_emoji(report.btc_direction)
    risk_emoji = _status_emoji(report.risk_appetite)
    trade_emoji = _status_emoji(report.tradable)
    btc_price = _format_price(report.btc_price, decimals=2)
    dxy_text = _compact_quote_line(report.dxy)
    us10y_text = _compact_yield_line(report.us10y)
    us2y_text = _compact_yield_line(report.us2y)
    nq_text = _compact_quote_line(report.nq)
    gold_text = _compact_quote_line(report.gold)
    etf_total = _format_signed(report.etf_flow.total, digits=1, suffix="M") if report.etf_flow else "数据暂不可用"
    etf_date = report.etf_flow.flow_date.isoformat() if report.etf_flow and report.etf_flow.flow_date else "数据暂不可用"

    macro_fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**💵 DXY**\n{dxy_text}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**🏦 US10Y**\n{us10y_text}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**🏦 US02Y**\n{us2y_text}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**📈 纳指期货**\n{nq_text}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**🥇 黄金**\n{gold_text}"}},
    ]

    etf_fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**BTC ETF**\n{etf_total}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**日期**\n{etf_date}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**机构判断**\n{_render_etf_judgement(report.etf_flow)}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**IBIT**\n{_compact_etf_value(report.etf_flow, 'IBIT')}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**FBTC**\n{_compact_etf_value(report.etf_flow, 'FBTC')}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**ARKB**\n{_compact_etf_value(report.etf_flow, 'ARKB')}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**BITB**\n{_compact_etf_value(report.etf_flow, 'BITB')}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**GBTC**\n{_compact_etf_value(report.etf_flow, 'GBTC')}"}},
    ]

    structure_lines = []
    for structure in report.structures:
        timeframe = structure.timeframe.upper()
        if timeframe == "15M":
            timeframe = "15M"
        line = f"**{timeframe}：** {structure.regime}｜压力 {_format_price(structure.resistance, decimals=0)}｜支撑 {_format_price(structure.support, decimals=0)}"
        structure_lines.append(line)
    structure_lines.append(f"成交量：{_volume_label(report.structures)}")

    reminder_lines = "\n".join([
        "- 不追涨杀跌",
        "- 跌破支撑不盲目抄底",
        "- 扫损后收回，等待回踩确认",
        "- 方向不明确，只观察",
    ])

    raw_lines = [
        f"- BTC ?????{btc_price}",
        f"- DXY ???{_raw_quote_data(report.dxy)}",
        f"- US10Y ???{_raw_quote_data(report.us10y)}",
        f"- US02Y ???{_raw_quote_data(report.us2y)}",
        f"- ???? ???{_raw_quote_data(report.nq)}",
        f"- ?? ???{_raw_quote_data(report.gold)}",
        f"- ETF ???{_raw_etf_data(report.etf_flow)}",
        f"- BTC ?????{_raw_structure_data(report.structures)}",
        f"- ?????macro={report.macro_score}, btc={report.btc_score}",
        f"- ?????workflow={os.getenv('GITHUB_WORKFLOW', 'local')}, run_id={os.getenv('GITHUB_RUN_ID', 'local')}, attempt={os.getenv('GITHUB_RUN_ATTEMPT', '1')}",
    ]

    return {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "📊 每日市场简报",
                },
                "subtitle": {
                    "tag": "plain_text",
                    "content": "BTC / 美股 / 黄金 / 美元 / ETF 资金流",
                },
                "template": summary_color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**显示时间：** {report.generated_at:%Y-%m-%d %H:%M CST}\n"
                            f"**BTC 当前价格：** {btc_price}\n"
                            f"**今日风险偏好：** {risk_emoji} {report.risk_appetite}\n"
                            f"**BTC方向：** {summary_emoji} {report.btc_direction}\n"
                            f"**交易建议：** {trade_emoji} {report.tradable}"
                        ),
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "fields": macro_fields,
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**🏛️ 机构资金**",
                    },
                },
                {
                    "tag": "div",
                    "fields": etf_fields,
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**📉 BTC 技术结构**\n" + "\n".join(structure_lines),
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**⚠️ 交易提醒**\n" + reminder_lines,
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**原始数据字段**\n" + "\n".join(raw_lines),
                    },
                },
            ],
        },
    }


class DailyMarketMonitorService:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.timezone = self._load_timezone(settings.market_monitor_timezone)
        self.binance = BinanceClient(
            rest_base_url=settings.binance_rest_base_url,
            ws_base_url=settings.binance_ws_base_url,
            futures_ws_base_url=settings.binance_futures_ws_base_url,
        )

    def build_report(self, now: datetime | None = None) -> DailyMarketBrief:
        generated_at = self._now(now)
        btc_price, btc_change_pct = self._fetch_btc_spot()
        dxy = self._fetch_yahoo_quote(_YAHOO_DXY_SYMBOLS, "美元指数 DXY")
        us10y = self._fetch_fred_yield(_FRED_10Y_SERIES, "US10Y")
        us2y = self._fetch_fred_yield(_FRED_2Y_SERIES, "US02Y")
        nq = self._fetch_yahoo_quote(_YAHOO_NQ_SYMBOLS, "纳斯达克 100 期货")
        gold = self._fetch_yahoo_quote(_YAHOO_GOLD_SYMBOLS, "黄金 XAUUSD")
        etf_flow = self._fetch_btc_etf_flow()
        structures = [
            self._safe_analyze_timeframe("4h", limit=180),
            self._safe_analyze_timeframe("1h", limit=240),
            self._safe_analyze_timeframe("15m", limit=240),
        ]
        macro_score = self._score_macro(dxy, us10y, us2y, nq, gold)
        btc_score = self._score_btc(structures, etf_flow, macro_score, btc_change_pct)
        risk_appetite = self._label_risk_appetite(macro_score)
        btc_direction = self._label_btc_direction(btc_score)
        tradable = self._label_tradable(btc_score, macro_score, structures, etf_flow)
        reminders = [
            "不要追涨杀跌",
            "如果 BTC 跌破关键支撑，不做盲目抄底",
            "如果只是扫损后快速收回，可以等待回踩确认",
            "没有明确方向时，只观察不交易",
        ]
        return DailyMarketBrief(
            generated_at=generated_at,
            btc_price=btc_price,
            dxy=dxy,
            us10y=us10y,
            us2y=us2y,
            nq=nq,
            gold=gold,
            etf_flow=etf_flow,
            structures=structures,
            macro_score=macro_score,
            btc_score=btc_score,
            risk_appetite=risk_appetite,
            btc_direction=btc_direction,
            tradable=tradable,
            reminder_lines=reminders,
        )

    def send_report(self, report: DailyMarketBrief) -> DeliveryResult:
        webhook = settings.market_monitor_feishu_webhook_url.strip()
        if not webhook:
            return DeliveryResult(sent=False, channel="feishu", detail="FEISHU webhook ?????????")

        payload = buildMarketBriefCard(report)
        timestamp = str(int(time.time()))
        secret = settings.market_monitor_feishu_secret.strip()
        if secret:
            payload["timestamp"] = timestamp
            payload["sign"] = self._feishu_sign(timestamp, secret)

        request = Request(
            webhook,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "MarketMind/0.1"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:
            return DeliveryResult(sent=False, channel="feishu", detail=f"???????{exc}")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return DeliveryResult(sent=True, channel="feishu", detail="???????????? JSON")
        if int(parsed.get("code", 0)) != 0:
            return DeliveryResult(sent=False, channel="feishu", detail=f"???????{parsed}")
        return DeliveryResult(sent=True, channel="feishu", detail="????????")

    def run_once(self) -> tuple[DailyMarketBrief, DeliveryResult]:
        report = self.build_report()
        delivery = self.send_report(report)
        return report, delivery

    def _fetch_btc_spot(self) -> tuple[float | None, float | None]:
        try:
            ticker = self.binance.fetch_24h_ticker("BTCUSDT")
        except Exception:
            try:
                quote = self._fetch_yahoo_quote(["BTC-USD"], "BTC")
                return quote.price, quote.change_pct
            except Exception:
                return None, None
        return ticker.last_price, ticker.price_change_percent

    def _fetch_yahoo_quote(self, symbols: list[str], label: str) -> QuoteSnapshot | None:
        last_error: Exception | None = None
        for symbol in symbols:
            try:
                payload = self._get_json(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
                    {
                        "interval": "1d",
                        "range": "5d",
                        "includePrePost": "false",
                        "events": "div,splits",
                    },
                )
                result = payload.get("chart", {}).get("result", [])
                if not result:
                    continue
                chart = result[0]
                meta = chart.get("meta", {})
                indicators = chart.get("indicators", {})
                quote_data = (indicators.get("quote") or [{}])[0]
                closes = [value for value in (quote_data.get("close") or []) if value is not None]
                timestamps = chart.get("timestamp") or []
                price = _first_number(
                    meta.get("regularMarketPrice"),
                    closes[-1] if closes else None,
                    meta.get("previousClose"),
                )
                previous_close = _first_number(meta.get("chartPreviousClose"), _previous_non_null(closes))
                change = None
                change_pct = None
                if price is not None and previous_close not in (None, 0):
                    change = price - previous_close
                    change_pct = change / previous_close * 100.0
                as_of = None
                if meta.get("regularMarketTime"):
                    as_of = datetime.fromtimestamp(int(meta["regularMarketTime"]), tz=timezone.utc)
                elif timestamps:
                    as_of = datetime.fromtimestamp(int(timestamps[-1]), tz=timezone.utc)
                return QuoteSnapshot(
                    label=label,
                    symbol=symbol,
                    price=price,
                    previous_close=previous_close,
                    change=change,
                    change_pct=change_pct,
                    as_of=as_of,
                    source=f"Yahoo Finance / chart API ({symbol})",
                )
            except Exception as exc:
                last_error = exc
                continue
        if last_error is not None:
            return None
        return None

    def _fetch_fred_yield(self, series_id: str, label: str) -> QuoteSnapshot | None:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        try:
            text = self._get_text(url)
        except Exception:
            return self._fetch_treasury_yield(series_id, label)

        rows = list(csv.DictReader(text.splitlines()))
        values: list[tuple[date, float]] = []
        for row in rows:
            raw_value = (row.get("VALUE") or "").strip()
            if not raw_value or raw_value == ".":
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            raw_date = (row.get("DATE") or "").strip()
            try:
                row_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            values.append((row_date, value))

        if not values:
            return self._fetch_treasury_yield(series_id, label)
        current_date, current_value = values[-1]
        previous_value = values[-2][1] if len(values) >= 2 else None
        change = current_value - previous_value if previous_value is not None else None
        change_pct = change / previous_value * 100.0 if previous_value not in (None, 0) and change is not None else None
        return QuoteSnapshot(
            label=label,
            symbol=series_id,
            price=current_value,
            previous_close=previous_value,
            change=change,
            change_pct=change_pct,
            as_of=datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
            source=f"FRED / {series_id}",
            unit="yield",
        )

    def _fetch_treasury_yield(self, series_id: str, label: str) -> QuoteSnapshot | None:
        try:
            html_text = self._get_text(
                _TREASURY_DAILY_YIELD_URL,
                headers=self._browser_headers(
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=_TREASURY_DAILY_YIELD_URL,
                ),
            )
        except Exception:
            return None

        table = _TreasuryYieldTable.parse(html_text)
        current_value = table.latest_value(series_id)
        previous_value = table.previous_value(series_id)
        if current_value is None or table.latest_date is None:
            return None

        change = current_value - previous_value if previous_value is not None else None
        change_pct = change / previous_value * 100.0 if previous_value not in (None, 0) and change is not None else None
        return QuoteSnapshot(
            label=label,
            symbol=series_id,
            price=current_value,
            previous_close=previous_value,
            change=change,
            change_pct=change_pct,
            as_of=datetime.combine(table.latest_date, datetime.min.time(), tzinfo=timezone.utc),
            source="U.S. Treasury / daily treasury yield curve",
            unit="yield",
        )

    def _fetch_btc_etf_flow(self) -> EtfFlowSnapshot | None:
        try:
            html_text = self._get_text(_FARSIDE_BTC_ETF_URL)
        except Exception:
            return None

        nodes = _TextNodeExtractor.extract(html_text)
        rows = _parse_farside_rows(nodes)
        if not rows:
            return None
        latest_date, latest_values = rows[-1]
        previous_total = rows[-2][1][-1] if len(rows) >= 2 else None
        funds = [
            "IBIT",
            "FBTC",
            "BITB",
            "ARKB",
            "BTCO",
            "EZBC",
            "BRRR",
            "HODL",
            "BTCW",
            "MSBT",
            "GBTC",
            "BTC",
            "Total",
        ]
        holdings = {funds[index]: latest_values[index] for index in range(min(len(funds), len(latest_values)))}
        total = holdings.get("Total")
        flow_date = None
        try:
            flow_date = datetime.strptime(latest_date, "%d %b %Y").date()
        except ValueError:
            flow_date = None
        return EtfFlowSnapshot(
            flow_date=flow_date,
            total=total,
            holdings=holdings,
            source=_FARSIDE_BTC_ETF_URL,
            recent_total=previous_total,
        )

    def _analyze_timeframe(self, timeframe: str, limit: int) -> TimeframeStructure:
        page = self.binance.fetch_klines("BTCUSDT", timeframe, limit=limit)
        candles = page.candles
        if len(candles) < 30:
            raise RuntimeError(f"Not enough BTC candles for {timeframe}")

        closes = [candle.close for candle in candles]
        highs = [candle.high for candle in candles]
        lows = [candle.low for candle in candles]
        volumes = [candle.volume for candle in candles]
        last_close = closes[-1]
        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50)
        ema100 = _ema(closes, 100)
        if ema20 is None or ema50 is None or ema100 is None:
            raise RuntimeError(f"EMA calculation failed for {timeframe}")
        above_ema20 = last_close >= ema20
        above_ema50 = last_close >= ema50
        above_ema100 = last_close >= ema100

        lookback = min(20, len(candles) - 1)
        recent_window = candles[-(lookback + 1) : -1]
        support = min(candle.low for candle in recent_window) if recent_window else min(lows[:-1])
        resistance = max(candle.high for candle in recent_window) if recent_window else max(highs[:-1])
        latest = candles[-1]
        average_volume = statistics.fmean(volumes[-(lookback + 1) : -1]) if lookback and len(volumes) > 1 else statistics.fmean(volumes)
        volume_ratio = latest.volume / average_volume if average_volume else 0.0

        bullish_sweep = latest.low < support * 0.999 and latest.close > support and latest.close >= latest.open
        bearish_sweep = latest.high > resistance * 1.001 and latest.close < resistance and latest.close <= latest.open
        breakout = None
        if latest.close > resistance * 1.001:
            breakout = "放量突破" if volume_ratio >= 1.5 else "突破压力位"
        elif latest.close < support * 0.999:
            breakout = "跌破关键支撑"
        sweep = None
        if bullish_sweep:
            sweep = "下探流动性后快速收回"
        elif bearish_sweep:
            sweep = "上探流动性后回落"

        regime = _timeframe_regime(above_ema20, above_ema50, above_ema100)
        summary_parts = [
            f"收盘 {last_close:,.2f}",
            f"EMA20/50/100 { _ema_side(above_ema20) } / { _ema_side(above_ema50) } / { _ema_side(above_ema100) }",
            f"结构 {regime}",
            f"支撑 {support:,.2f}",
            f"压力 {resistance:,.2f}",
        ]
        if breakout:
            summary_parts.append(breakout)
        if sweep:
            summary_parts.append(sweep)
        if volume_ratio >= 1.5:
            summary_parts.append(f"成交量 {volume_ratio:.1f}x")
        elif volume_ratio <= 0.7:
            summary_parts.append(f"成交量偏弱 {volume_ratio:.1f}x")

        return TimeframeStructure(
            timeframe=timeframe,
            last_close=last_close,
            ema20=ema20,
            ema50=ema50,
            ema100=ema100,
            above_ema20=above_ema20,
            above_ema50=above_ema50,
            above_ema100=above_ema100,
            support=support,
            resistance=resistance,
            volume_ratio=volume_ratio,
            sweep=sweep,
            breakout=breakout,
            regime=regime,
            summary="；".join(summary_parts),
        )

    def _safe_analyze_timeframe(self, timeframe: str, limit: int) -> TimeframeStructure:
        try:
            return self._analyze_timeframe(timeframe, limit)
        except Exception as exc:
            return TimeframeStructure(
                timeframe=timeframe,
                last_close=None,
                ema20=None,
                ema50=None,
                ema100=None,
                above_ema20=None,
                above_ema50=None,
                above_ema100=None,
                support=None,
                resistance=None,
                volume_ratio=None,
                sweep=None,
                breakout=None,
                regime="数据暂不可用",
                summary=f"数据暂不可用（{exc}）",
            )

    def _score_macro(
        self,
        dxy: QuoteSnapshot | None,
        us10y: QuoteSnapshot | None,
        us2y: QuoteSnapshot | None,
        nq: QuoteSnapshot | None,
        gold: QuoteSnapshot | None,
    ) -> int:
        score = 0
        if dxy and dxy.change_pct is not None:
            score += -1 if dxy.change_pct > 0.15 else 1 if dxy.change_pct < -0.15 else 0
        if us10y and us2y and us10y.change is not None and us2y.change is not None:
            avg_change = (us10y.change + us2y.change) / 2.0
            score += -1 if avg_change > 0.02 else 1 if avg_change < -0.02 else 0
        elif us10y and us10y.change is not None:
            score += -1 if us10y.change > 0.02 else 1 if us10y.change < -0.02 else 0
        if nq and nq.change_pct is not None:
            score += 1 if nq.change_pct > 0.3 else -1 if nq.change_pct < -0.3 else 0
        if gold and gold.change_pct is not None and dxy and dxy.change_pct is not None:
            if gold.change_pct > 0 and dxy.change_pct < 0:
                score += 1
            elif gold.change_pct > 0 and dxy.change_pct > 0:
                score -= 1
        return score

    def _score_btc(
        self,
        structures: list[TimeframeStructure],
        etf_flow: EtfFlowSnapshot | None,
        macro_score: int,
        btc_change_pct: float | None,
    ) -> int:
        score = 0
        for structure in structures:
            if structure.above_ema20 and structure.above_ema50 and structure.above_ema100:
                score += 1
            elif structure.above_ema20 is False and structure.above_ema50 is False and structure.above_ema100 is False:
                score -= 1
            if structure.breakout in {"突破压力位", "放量突破"}:
                score += 1
            elif structure.breakout == "跌破关键支撑":
                score -= 1
            if structure.sweep == "下探流动性后快速收回":
                score += 1
            elif structure.sweep == "上探流动性后回落":
                score -= 1
        if etf_flow and etf_flow.total is not None:
            if etf_flow.total >= 100:
                score += 2
            elif etf_flow.total >= 25:
                score += 1
            elif etf_flow.total <= -100:
                score -= 2
            elif etf_flow.total <= -25:
                score -= 1
        if btc_change_pct is not None:
            if btc_change_pct >= 2:
                score += 1
            elif btc_change_pct <= -2:
                score -= 1
        score += 1 if macro_score >= 2 else -1 if macro_score <= -2 else 0
        return score

    def _label_risk_appetite(self, macro_score: int) -> str:
        if macro_score >= 2:
            return "强"
        if macro_score <= -2:
            return "弱"
        return "中性"

    def _label_btc_direction(self, btc_score: int) -> str:
        if btc_score >= 4:
            return "偏多"
        if btc_score <= -4:
            return "偏空"
        return "震荡"

    def _label_tradable(
        self,
        btc_score: int,
        macro_score: int,
        structures: list[TimeframeStructure],
        etf_flow: EtfFlowSnapshot | None,
    ) -> str:
        all_bullish = any(structure.regime == "多头排列" for structure in structures)
        all_bearish = any(structure.regime == "空头排列" for structure in structures)
        etf_supportive = etf_flow is not None and etf_flow.total is not None and etf_flow.total > 0
        if btc_score >= 5 and (macro_score >= 1 or etf_supportive) and all_bullish:
            return "适合"
        if btc_score <= -5 or (macro_score <= -2 and all_bearish):
            return "不适合"
        return "等待确认"

    def _now(self, now: datetime | None = None) -> datetime:
        if now is None:
            return datetime.now(self.timezone)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.timezone)
        return now.astimezone(self.timezone)

    def _get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        request = Request(url, headers=headers or self._browser_headers())
        with urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}" + "&".join(
                f"{quote(str(key), safe='')}={quote(str(value), safe='')}" for key, value in params.items()
            )
        text = self._get_text(url, headers=self._browser_headers(accept="application/json,text/plain,*/*"))
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected JSON payload from {url}")
        return payload

    def _browser_headers(self, accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", referer: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _feishu_sign(self, timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _load_timezone(self, timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            return ZoneInfo("UTC")


class _TextNodeExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[str] = []

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.nodes.append(value)

    @classmethod
    def extract(cls, html_text: str) -> list[str]:
        parser = cls()
        parser.feed(html_text)
        return parser.nodes


def _parse_farside_rows(nodes: list[str]) -> list[tuple[str, list[float | None]]]:
    rows: list[tuple[str, list[float | None]]] = []
    idx = 0
    while idx < len(nodes):
        token = nodes[idx]
        if _is_date_token(token):
            date_token = token
            values: list[float | None] = []
            idx += 1
            while idx < len(nodes):
                candidate = nodes[idx]
                if _is_date_token(candidate):
                    break
                numeric_value = _parse_flow_value(candidate)
                if numeric_value is not None or candidate in {"-", "—"}:
                    values.append(numeric_value)
                if len(values) >= 13:
                    idx += 1
                    break
                idx += 1
            if len(values) >= 13:
                rows.append((date_token, values[:13]))
            continue
        idx += 1
    return rows


def _is_date_token(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2} [A-Za-z]{3} \d{4}", value))


def _parse_flow_value(value: str) -> float | None:
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return -parsed if negative else parsed


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    ema_value = statistics.fmean(values[:period])
    multiplier = 2.0 / (period + 1)
    for value in values[period:]:
        ema_value = (value - ema_value) * multiplier + ema_value
    return ema_value


def _timeframe_regime(above_ema20: bool, above_ema50: bool, above_ema100: bool) -> str:
    if above_ema20 and above_ema50 and above_ema100:
        return "多头排列"
    if not above_ema20 and not above_ema50 and not above_ema100:
        return "空头排列"
    return "结构中性"


def _ema_side(is_above: bool) -> str:
    return "上方" if is_above else "下方"


def _format_signed(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None or math.isnan(value):
        return "数据暂不可用"
    return f"{value:+.{digits}f}{suffix}"


def _format_price(value: float | None, decimals: int = 2) -> str:
    if value is None or math.isnan(value):
        return "数据暂不可用"
    return f"{value:,.{decimals}f}"


def _format_price_change(quote: QuoteSnapshot | None) -> str:
    if quote is None or quote.price is None:
        return "数据暂不可用"
    if quote.unit == "yield":
        change_bp = (quote.change or 0.0) * 100.0 if quote.change is not None else None
        return f"{quote.price:.2f}% ({_format_signed(change_bp, digits=1, suffix='bp') if change_bp is not None else '数据暂不可用'})"
    if quote.change_pct is None:
        return f"{_format_price(quote.price)}"
    return f"{_format_price(quote.price)} ({_format_signed(quote.change_pct, digits=2, suffix='%')})"


def _render_quote(quote: QuoteSnapshot | None) -> str:
    if quote is None:
        return "数据暂不可用"
    direction = _quote_direction(quote)
    return f"{_format_price_change(quote)}，{direction}"


def _render_yield_pair(us10y: QuoteSnapshot | None, us2y: QuoteSnapshot | None) -> str:
    parts = [
        f"US10Y {_format_price_change(us10y)}",
        f"US02Y {_format_price_change(us2y)}",
    ]
    if us10y is not None and us2y is not None and us10y.change is not None and us2y.change is not None:
        average_change_bp = ((us10y.change + us2y.change) / 2.0) * 100.0
        if average_change_bp > 1:
            parts.append("利率压力上升")
        elif average_change_bp < -1:
            parts.append("利率压力下降")
        else:
            parts.append("利率压力中性")
    return " / ".join(parts)


def _render_gold(gold: QuoteSnapshot | None, dxy: QuoteSnapshot | None) -> str:
    if gold is None:
        return "数据暂不可用"
    direction = _quote_direction(gold)
    if dxy is None or dxy.change_pct is None or gold.change_pct is None:
        return f"{_format_price_change(gold)}，{direction}"
    if gold.change_pct > 0 and dxy.change_pct < 0:
        return f"{_format_price_change(gold)}，黄金涨 + 美元跌 = 美元走弱"
    if gold.change_pct > 0 and dxy.change_pct > 0:
        return f"{_format_price_change(gold)}，黄金涨 + 美元涨 = 避险资金流入"
    return f"{_format_price_change(gold)}，{direction}"


def _render_etf_total(snapshot: EtfFlowSnapshot | None) -> str:
    if snapshot is None or snapshot.total is None:
        return "数据暂不可用"
    flow_date = f"（{snapshot.flow_date:%Y-%m-%d}）" if snapshot.flow_date else ""
    return f"{_format_signed(snapshot.total, digits=1, suffix='M')} {flow_date}".strip()


def _render_etf_holdings(snapshot: EtfFlowSnapshot | None) -> str:
    if snapshot is None:
        return "数据暂不可用"
    order = ["IBIT", "FBTC", "ARKB", "BITB", "GBTC", "BTC", "BTCO", "EZBC", "BRRR", "HODL", "BTCW", "MSBT"]
    pieces: list[str] = []
    for fund in order:
        value = snapshot.holdings.get(fund)
        if value is None and fund not in snapshot.holdings:
            continue
        formatted_value = f"{_format_signed(value, digits=1, suffix='M')}" if value is not None else "-"
        pieces.append(f"{fund} {formatted_value}")
    return " | ".join(pieces[:8]) if pieces else "数据暂不可用"


def _render_etf_judgement(snapshot: EtfFlowSnapshot | None) -> str:
    if snapshot is None or snapshot.total is None:
        return "数据暂不可用"
    total = snapshot.total
    recent = snapshot.recent_total
    if total >= 100:
        return "机构持续买入"
    if total <= -100:
        return "机构流出"
    if recent is not None and recent < 0 and total < 0:
        return "机构偏流出"
    if recent is not None and recent > 0 and total > 0:
        return "机构偏买入"
    return "无明显方向"


def _quote_direction(quote: QuoteSnapshot) -> str:
    if quote.change_pct is None:
        return "方向不明"
    if quote.label.startswith("美元") or quote.label == "BTC":
        if quote.change_pct > 0.15:
            return "偏强"
        if quote.change_pct < -0.15:
            return "偏弱"
        return "中性"
    if quote.label.startswith("纳指"):
        if quote.change_pct > 0.3:
            return "科技股风险偏好"
        if quote.change_pct < -0.3:
            return "科技股风险回避"
        return "科技股中性"
    if quote.label.startswith("黄金"):
        if quote.change_pct > 0.2:
            return "避险偏强"
        if quote.change_pct < -0.2:
            return "避险偏弱"
        return "中性"
    return "中性"


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


class _TreasuryYieldTable:
    def __init__(self, latest_date: date | None, rows: list[dict[str, str]]) -> None:
        self.latest_date = latest_date
        self.rows = rows

    @classmethod
    def parse(cls, html_text: str) -> "_TreasuryYieldTable":
        table_match = re.search(
            r'<table class="usa-table views-table views-view-table cols-26 sticky-enabled">(.*?)</table>',
            html_text,
            flags=re.S,
        )
        if table_match is None:
            return cls(None, [])

        table_html = table_match.group(1)
        header_cells = re.findall(r"<th[^>]*>(.*?)</th>", table_html, flags=re.S)
        headers = [_strip_tags(cell) for cell in header_cells]
        row_matches = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.S)

        data_rows: list[dict[str, str]] = []
        for row_html in row_matches[1:]:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S)
            if len(cells) < len(headers):
                continue
            values = [_strip_tags(cell) for cell in cells[: len(headers)]]
            data_rows.append({headers[i]: values[i] for i in range(len(headers))})

        latest_date = None
        for row in reversed(data_rows):
            parsed_date = _parse_us_date(row.get("Date"))
            if parsed_date is not None:
                latest_date = parsed_date
                break

        return cls(latest_date, data_rows)

    def latest_value(self, series_id: str) -> float | None:
        column = _TREASURY_COLUMN_MAP.get(series_id)
        if column is None:
            return None
        for row in reversed(self.rows):
            value = _parse_numeric(row.get(column))
            if value is not None:
                return value
        return None

    def previous_value(self, series_id: str) -> float | None:
        column = _TREASURY_COLUMN_MAP.get(series_id)
        if column is None:
            return None
        seen_latest = False
        for row in reversed(self.rows):
            value = _parse_numeric(row.get(column))
            if value is None:
                continue
            if not seen_latest:
                seen_latest = True
                continue
            return value
        return None


_TREASURY_COLUMN_MAP = {
    "DGS10": "10 Yr",
    "DGS2": "2 Yr",
}


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).replace("\xa0", " ").strip()


def _parse_us_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        return None


def _parse_numeric(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned == "N/A":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _previous_non_null(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    for value in reversed(values[:-1]):
        if value is not None:
            return value
    return None


def _compact_quote_line(quote: QuoteSnapshot | None) -> str:
    if quote is None or quote.price is None:
        return '??????'
    price = _format_price(quote.price, decimals=2)
    if quote.change_pct is None:
        return price
    return f"{price} {_format_signed(quote.change_pct, digits=2, suffix='%')} {_quote_direction(quote)}"


def _compact_yield_line(quote: QuoteSnapshot | None) -> str:
    if quote is None or quote.price is None:
        return '??????'
    if quote.change is None:
        return f"{quote.price:.2f}%"
    return f"{quote.price:.2f}% {_format_signed(quote.change * 100.0, digits=1, suffix='bp')} {_yield_direction(quote)}"


def _yield_direction(quote: QuoteSnapshot) -> str:
    if quote.change is None:
        return '??'
    if quote.change > 0.02:
        return '??????'
    if quote.change < -0.02:
        return '??????'
    return '??????'


def _compact_etf_value(snapshot: EtfFlowSnapshot | None, symbol: str) -> str:
    if snapshot is None:
        return '??????'
    value = snapshot.holdings.get(symbol)
    if value is None:
        return '-'
    return _format_signed(value, digits=1, suffix='M')


def _volume_label(structures: list[TimeframeStructure]) -> str:
    values = [structure.volume_ratio for structure in structures if structure.volume_ratio is not None]
    if not values:
        return '????????'
    average = sum(values) / len(values)
    if average >= 1.2:
        return '????'
    if average <= 0.8:
        return '????'
    return '????'


def _summary_emoji(label: str) -> str:
    if '??' in label:
        return '??'
    if '??' in label:
        return '??'
    return '??'


def _status_emoji(label: str) -> str:
    if '??' in label or '??' in label or '??' in label:
        return '??'
    if '???' in label or '??' in label or '?' in label:
        return '??'
    if '??' in label or '??' in label or '??' in label:
        return '??'
    return '?'


def _card_template_for_report(report: DailyMarketBrief) -> str:
    if report.tradable == '???' or report.btc_direction == '??' or report.risk_appetite == '?':
        return 'red'
    if report.tradable == '??' or report.btc_direction == '??' or report.risk_appetite == '?':
        return 'green'
    return 'yellow'


def _raw_quote_data(quote: QuoteSnapshot | None) -> str:
    if quote is None or quote.price is None:
        return 'null'
    return (
        f"symbol={quote.symbol}, price={_format_price(quote.price, decimals=2)}, "
        f"change={_format_signed(quote.change_pct, digits=2, suffix='%') if quote.change_pct is not None else 'null'}, "
        f"source={quote.source}"
    )


def _raw_etf_data(snapshot: EtfFlowSnapshot | None) -> str:
    if snapshot is None:
        return 'null'
    major = ', '.join(f"{key}={_format_signed(value, digits=1, suffix='M') if value is not None else 'null'}" for key, value in list(snapshot.holdings.items())[:5])
    date_value = snapshot.flow_date.isoformat() if snapshot.flow_date else 'null'
    return f"date={date_value}, total={_format_signed(snapshot.total, digits=1, suffix='M') if snapshot.total is not None else 'null'}, {major}"


def _raw_structure_data(structures: list[TimeframeStructure]) -> str:
    parts: list[str] = []
    for structure in structures:
        if structure.volume_ratio is None:
            parts.append(f"{structure.timeframe}:{structure.regime}, volume=null")
            continue
        parts.append(
            f"{structure.timeframe}:{structure.regime}, close={_format_price(structure.last_close, decimals=2) if structure.last_close is not None else 'null'}, "
            f"support={_format_price(structure.support, decimals=0) if structure.support is not None else 'null'}, "
            f"resistance={_format_price(structure.resistance, decimals=0) if structure.resistance is not None else 'null'}, "
            f"volume={structure.volume_ratio:.2f}x"
        )
    return ' | '.join(parts)

