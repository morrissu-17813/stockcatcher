import os
import json
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone, time as datetime_time

import numpy as np
import pandas as pd

from dotenv import load_dotenv
import requests

_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=_ENV_PATH)

FUGLE_API_KEY = "NTMyNDYzMzItZDkxYS00MmQwLThiMGEtMTY2NjkyZTM4MTExIGYzNDRjNWNmLTdhYWQtNDc4Ny1hODVmLTQ5ZjZhOWUwYjYzZA=="
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE"
TELEGRAM_BOT_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
TELEGRAM_CHAT_ID = "1087480334"
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))
MARKET_OPEN = datetime_time(9, 0)
MARKET_CLOSE = datetime_time(13, 30)
MONITOR_STOP_TIME = datetime_time(13, 35)
FUBON_RANK_URL = "https://warrants.fbs.com.tw/want/data/getWRankResult.aspx"
FUBON_RANK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://warrants.fbs.com.tw/want/wRank.aspx",
}
KLINE_TIMEFRAME_MINUTES = 5
KLINE_VOLUME_MULTIPLIER = 1.2
OPENING_KLINE_VOLUME_MULTIPLIER = 1.8
KLINE_MIN_VOLUME_HISTORY = 5
WARRANT_VOLUME_GROWTH_PERCENT = 20.0
WARRANT_VOLUME_GROWTH_MINIMUM = 500


def get_taipei_now() -> datetime:
    return datetime.now(TAIPEI_TIMEZONE)


def is_market_hours(now: Optional[datetime] = None) -> bool:
    current = now or get_taipei_now()
    return current.weekday() < 5 and MARKET_OPEN <= current.time() <= MARKET_CLOSE


def is_opening_noise_period(now: Optional[datetime] = None) -> bool:
    current = now or get_taipei_now()
    return current.weekday() < 5 and MARKET_OPEN <= current.time() < datetime_time(9, 15)


def get_monitor_stop_at(started_at: Optional[datetime] = None) -> datetime:
    """取得本次手動啟動後的下一個交易日13:35停止時間。"""
    current = started_at or get_taipei_now()
    stop_date = current.date()
    if current.weekday() >= 5 or current.time() >= MONITOR_STOP_TIME:
        stop_date += timedelta(days=1)
        while stop_date.weekday() >= 5:
            stop_date += timedelta(days=1)
    return datetime.combine(stop_date, MONITOR_STOP_TIME, tzinfo=TAIPEI_TIMEZONE)


def detect_effective_3k_breakout(bars: List[Dict[str, Any]], volume_multiplier: float = KLINE_VOLUME_MULTIPLIER) -> Optional[Dict[str, Any]]:
    """依 test_catchWarrant.py 判斷最後三根已收盤5分K的有效突破。"""
    if len(bars) < KLINE_MIN_VOLUME_HISTORY + 3:
        return None

    first_bar, second_bar, third_bar = bars[-3:]
    previous_bars = bars[:-3][-20:]
    if not previous_bars:
        return None

    breakout_price = max(float(first_bar["high"]), float(second_bar["high"]))
    previous_average_volume = sum(float(bar["volume"]) for bar in previous_bars) / len(previous_bars)
    required_volume = max(
        float(first_bar["volume"]),
        float(second_bar["volume"]),
        previous_average_volume * volume_multiplier,
    )
    third_close = float(third_bar["close"])
    third_volume = float(third_bar["volume"])
    if third_close <= breakout_price or third_volume <= required_volume:
        return None

    return {
        "bar_time": third_bar["date"],
        "breakout_price": breakout_price,
        "close": third_close,
        "volume": third_volume,
        "required_volume": required_volume,
        "volume_ratio": third_volume / previous_average_volume if previous_average_volume else 0.0,
        "stop_price": min(float(first_bar["low"]), float(second_bar["low"]), float(third_bar["low"])),
    }


def fetch_effective_3k_breakout(symbol: str, volume_multiplier: float = KLINE_VOLUME_MULTIPLIER) -> Optional[Dict[str, Any]]:
    """從 Fugle 取得5分K，只使用已收盤資料判斷有效3K。"""
    if not FUGLE_API_KEY:
        return None

    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{symbol}"
    response = requests.get(
        url,
        headers={"X-API-KEY": FUGLE_API_KEY},
        params={"timeframe": str(KLINE_TIMEFRAME_MINUTES), "limit": "200"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    raw_bars = payload.get("data", payload.get("candles", []))
    if not isinstance(raw_bars, list):
        return None

    completed_bars: List[Dict[str, Any]] = []
    now_timestamp = get_taipei_now().timestamp()
    for raw_bar in raw_bars:
        try:
            bar = dict(raw_bar)
            bar["date"] = pd.to_datetime(bar["date"], utc=True)
            for field in ("high", "low", "close", "volume"):
                bar[field] = float(bar[field])
            if bar["date"].timestamp() + KLINE_TIMEFRAME_MINUTES * 60 <= now_timestamp:
                completed_bars.append(bar)
        except (KeyError, TypeError, ValueError):
            continue

    completed_bars.sort(key=lambda bar: bar["date"])
    return detect_effective_3k_breakout(completed_bars, volume_multiplier)


def fetch_effective_3k_breakouts(
    symbols: List[str],
    volume_multiplier: float = KLINE_VOLUME_MULTIPLIER,
    max_workers: int = 5,
) -> Dict[str, Dict[str, Any]]:
    """並行取得命中標的的已收盤5分K，避免逐檔等待 Fugle 網路回應。"""
    results: Dict[str, Dict[str, Any]] = {}
    if not symbols:
        return results

    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as executor:
        futures = {
            executor.submit(fetch_effective_3k_breakout, symbol, volume_multiplier): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                signal = future.result()
            except (requests.RequestException, ValueError, TypeError):
                continue
            if signal:
                results[symbol] = signal
    return results


def send_telegram_message(text: str, chat_id: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
    """Send a plain text message to Telegram. Defaults to the project .env config, but accepts overrides."""
    bot_token = (token or TELEGRAM_BOT_TOKEN).strip()
    target_chat_id = str(chat_id or TELEGRAM_CHAT_ID).strip()
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing.")
    if not target_chat_id:
        raise ValueError("TELEGRAM_CHAT_ID is missing.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, data=payload, timeout=15)
    try:
        result = response.json()
    except ValueError:
        result = {"ok": False, "description": response.text}
    return {"status_code": response.status_code, "body": result}


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("*", "").replace("臺", "台").replace(" ", "")
    return text


def _safe_cast(value: Any, cast_type: type, default: Any = 0):
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("+", "").strip()
            if value in {"", "--", "-", "N/A", "null"}:
                return default
        return cast_type(value)
    except (TypeError, ValueError):
        return default


class FundamentalChipDataLayer:
    """
    免費資料層：內部人 > 三大法人 > 融資
    優先級：內部人買超 (最重要) > 三大法人淨買超 > 融資買超
    """

    @staticmethod
    def fetch_insider_buy_data(lookback_days: int = 30) -> Dict[str, Dict[str, Any]]:
        """
        從 FinMind API 抓董監事及經理人員進出持股(內部人買超)。
        使用 FinMind 免費 API，替代掉壞掉的 TWSE t187ap51_L。
        """
        try:
            if not FINMIND_TOKEN:
                return {}
            
            # FinMind API: 董監事法人購買股數(buy_volume)
            # Dataset: TaiwanStockInsiderTrading
            url = "https://api.finmindtrade.com/api/v4/data"
            headers = {"Authorization": f"Bearer {FINMIND_TOKEN}"}
            
            params = {
                "dataset": "TaiwanStockInsiderTrading",
                "data_id": "",  # 空值表示查詢全市場
                "start_date": (pd.Timestamp.now() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d"),
                "end_date": pd.Timestamp.now().strftime("%Y-%m-%d"),
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code != 200:
                return {}
            
            data = response.json()
            if data.get("status") != 0 or "data" not in data:
                return {}
            
            rows = data.get("data", [])
            if not isinstance(rows, list):
                return {}
        except Exception as e:
            print(f"[FinMind 內部人 API] 錯誤: {e}")
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue

            try:
                sid = str(row.get("stock_id", "")).strip()
                if not sid or len(sid) != 4:
                    continue
                
                # FinMind 返回的數據結構
                # "buy_volume" 購買股數 > "sell_volume" 賣出股數 = 買超
                buy_vol = float(row.get("buy_volume", 0))
                sell_vol = float(row.get("sell_volume", 0))
                net_buy = buy_vol - sell_vol
                
                # 只記錄買超的
                if net_buy <= 0:
                    continue
                
                date_str = row.get("date", "")
                person = row.get("trust_name", "") or row.get("name", "內部人")
                
                if sid not in result:
                    result[sid] = {
                        "symbol": sid,
                        "net_buy": 0.0,
                        "buy_count": 0,
                        "last_date": None,
                        "buy_names": [],
                        "buy_dates": set(),
                    }

                result[sid]["net_buy"] += net_buy
                result[sid]["buy_count"] += 1
                result[sid]["last_date"] = date_str
                if date_str:
                    result[sid]["buy_dates"].add(str(date_str)[:10])
                if person not in result[sid]["buy_names"]:
                    result[sid]["buy_names"].append(person)

            except Exception:
                continue

        for item in result.values():
            dates = sorted(item.pop("buy_dates", set()), reverse=True)
            streak = 0
            expected_date = pd.Timestamp(dates[0]) if dates else None
            for date_text in dates:
                current_date = pd.Timestamp(date_text)
                if expected_date is not None and current_date == expected_date:
                    streak += 1
                    expected_date -= pd.Timedelta(days=1)
                elif expected_date is not None and current_date < expected_date:
                    break
            item["buy_streak"] = streak
        return result

    @staticmethod
    def fetch_three_institutional_buy(lookback_days: int = 30) -> Dict[str, Dict[str, Any]]:
        """
        合併 TWSE 與 TPEx 最新三大法人資料。
        TPEx API 為當日快照，欄位使用其明細表的明確欄位索引。
        """
        result: Dict[str, Dict[str, Any]] = {}
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=lookback_days)

        def add_row(sid: Any, foreign: Any, investment: Any, dealer: Any, date_str: Any) -> None:
            symbol = str(sid).strip()
            if not re.fullmatch(r"\d{4}", symbol):
                return
            parsed_date = pd.to_datetime(date_str, errors="coerce") if date_str else pd.NaT
            if pd.notna(parsed_date) and parsed_date.tzinfo is None and parsed_date < cutoff:
                return

            foreign_value = _safe_cast(foreign, float, 0.0)
            investment_value = _safe_cast(investment, float, 0.0)
            dealer_value = _safe_cast(dealer, float, 0.0)
            item = result.setdefault(symbol, {
                "symbol": symbol,
                "foreign": 0.0,
                "investment": 0.0,
                "dealer": 0.0,
                "net_buy": 0.0,
                "last_date": None,
            })
            item["foreign"] += foreign_value
            item["investment"] += investment_value
            item["dealer"] += dealer_value
            item["net_buy"] += foreign_value + investment_value + dealer_value
            item["last_date"] = str(date_str)

        try:
            response = requests.get(
                "https://openapi.twse.com.tw/v1/opendata/t187ap40_L",
                timeout=30,
            )
            response.raise_for_status()
            rows = response.json()
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        add_row(
                            row.get("股票代號"),
                            row.get("外資買賣超", 0),
                            row.get("投信買賣超", 0),
                            row.get("自營商買賣超", 0),
                            row.get("成交日期", ""),
                        )
        except (requests.RequestException, ValueError, TypeError):
            pass

        try:
            response = requests.get(
                "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php",
                params={"l": "zh-tw", "o": "json"},
                headers={"User-Agent": FUBON_RANK_HEADERS["User-Agent"], "Referer": "https://www.tpex.org.tw/"},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            table = payload.get("tables", [])[0]
            for row in table.get("data", []):
                if not isinstance(row, list) or len(row) < 23:
                    continue
                add_row(
                    row[0],
                    row[10],
                    row[13],
                    row[22],
                    payload.get("date", ""),
                )
        except (requests.RequestException, ValueError, TypeError, IndexError, KeyError):
            pass

        return result

    @staticmethod
    def fetch_margin_buy(lookback_days: int = 30) -> Dict[str, Dict[str, Any]]:
        """
        從 TWSE 開放資料抓融資買超(大戶杠杆買進)。
        """
        try:
            url = "https://openapi.twse.com.tw/v1/opendata/t187ap49_L"
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                return {}
            rows = response.json()
            if not isinstance(rows, list):
                return {}
        except Exception:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=lookback_days)
        for row in rows:
            if not isinstance(row, dict):
                continue

            try:
                date_str = row.get("成交日期", "")
                if date_str:
                    row_date = pd.to_datetime(date_str, format="%Y/%m/%d", errors="coerce")
                    if row_date is None or row_date < cutoff:
                        continue
            except Exception:
                pass

            sid = str(row.get("股票代號", "")).strip()
            if not sid or len(sid) != 4:
                continue

            net_buy = _safe_cast(row.get("融資買超", 0), float, 0.0)
            if sid not in result:
                result[sid] = {
                    "symbol": sid,
                    "net_buy": 0.0,
                    "last_date": None,
                }

            result[sid]["net_buy"] += net_buy
            result[sid]["last_date"] = date_str

        return result

    @classmethod
    def rank_by_priority(cls, symbol_list: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        優先級排序：內部人買超 > 三大法人 > 融資買超
        返回每檔股票的籌碼信號強度評分
        """
        insider = cls.fetch_insider_buy_data(lookback_days=30)
        three_inst = cls.fetch_three_institutional_buy(lookback_days=30)
        margin = cls.fetch_margin_buy(lookback_days=30)

        result = {}
        for sid in symbol_list:
            sid = str(sid).strip()
            score = 0.0
            signals = {}

            if sid in insider and insider[sid]["net_buy"] > 0:
                insider_score = min(100.0, insider[sid]["net_buy"] / 1000.0)
                score += insider_score * 0.6
                signals["insider"] = {
                    "net_buy": insider[sid]["net_buy"],
                    "buy_count": insider[sid]["buy_count"],
                    "names": insider[sid]["buy_names"],
                    "score_contribution": insider_score * 0.6,
                }

            if sid in three_inst and three_inst[sid]["net_buy"] > 0:
                inst_score = min(100.0, three_inst[sid]["net_buy"] / 50_000_000.0)
                score += inst_score * 0.3
                signals["institutional"] = {
                    "foreign": three_inst[sid]["foreign"],
                    "investment": three_inst[sid]["investment"],
                    "dealer": three_inst[sid]["dealer"],
                    "net_buy": three_inst[sid]["net_buy"],
                    "score_contribution": inst_score * 0.3,
                }

            if sid in margin and margin[sid]["net_buy"] > 0:
                margin_score = min(100.0, margin[sid]["net_buy"] / 50_000_000.0)
                score += margin_score * 0.1
                signals["margin"] = {
                    "net_buy": margin[sid]["net_buy"],
                    "score_contribution": margin_score * 0.1,
                }

            if score > 0:
                result[sid] = {
                    "symbol": sid,
                    "chip_score": min(100.0, score),
                    "signals": signals,
                    "priority_rank": len([s for s in signals.keys() if signals[s].get("net_buy", 0) > 0]),
                }

        sorted_result = dict(sorted(result.items(), key=lambda item: item[1]["chip_score"], reverse=True))
        return sorted_result


class SignalResult(dict):
    """簡單資料結果格式，方便 Telegram / LINE 直接序列化輸出。"""

    def __getattr__(self, item):
        return self.get(item)


class TechnicalSignalEngine:
    """
    兩階段技術指標系統：
    1) 盤前預算：抓近 60 天歷史 K 線，算好技術指標與壓力/支撐位。
    2) 盤中：不再向網路 API 請求歷史資料，只更新記憶體中的即時 K 棒。

    這樣可以做到「完全無延遲」的盤中技術判斷，因為計算都是在記憶體內執行。
    """

    def __init__(self, api_key: str = None, timezone_offset: int = 8):
        self.api_key = api_key or FUGLE_API_KEY
        self.timezone_offset = timezone_offset
        self.cache: Dict[str, pd.DataFrame] = {}
        self.live_history: Dict[str, Dict[str, Any]] = {}

    def _now_tw(self) -> datetime:
        return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=self.timezone_offset)))

    def _request_json(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> Dict[str, Any]:
        headers = {"X-API-KEY": self.api_key}
        response = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
        if response.status_code != 200:
            raise RuntimeError(f"Fugle API request failed: {response.status_code} {response.text}")
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def fetch_historical_candles(
        self,
        symbol: str,
        timeframe: str = "D",
        lookback_days: int = 60,
        include_ohlcv: bool = True,
    ) -> pd.DataFrame:
        """
        盤前執行：一次抓取近 N 天歷史 K 線，預先算好技術指標。
        """
        symbol = str(symbol).strip()
        if not self.api_key:
            raise ValueError("FUGLE_API_KEY is not configured. Set FUGLE_API_KEY in env or .env")

        url = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol}"
        params = {"fields": "open,high,low,close,volume", "timeframe": timeframe}
        response = self._request_json(url, params=params)

        candles = response.get("candles", response.get("data", []))
        if not candles:
            raise ValueError(f"No historical candles returned for symbol {symbol}.")

        df = pd.DataFrame(candles)
        if df.empty:
            return df

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=True)
            df = df.sort_values("date").reset_index(drop=True)

        if lookback_days and "date" in df.columns:
            cutoff = pd.Timestamp.now(tz="UTC").tz_convert("Asia/Taipei") - pd.Timedelta(days=lookback_days)
            df = df[df["date"] >= cutoff].copy()

        if "volume" not in df.columns:
            df["volume"] = 0.0

        df = self._normalize_ohlcv(df)
        self.cache[symbol] = df
        return df

    def _normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

        for c in ["open", "high", "low", "close", "volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=True)
        else:
            df["date"] = pd.date_range(start=datetime.now() - timedelta(days=len(df)), periods=len(df), freq="D")

        df = df.sort_values("date").reset_index(drop=True)
        if "close" in df.columns:
            df["close"] = df["close"].replace(0, np.nan)
            df = df.dropna(subset=["close"]).reset_index(drop=True)
        return df

    def fetch_latest_quote(self, symbol: str) -> Dict[str, Any]:
        """只讀取即時報價，不抓歷史資料。"""
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
        payload = self._request_json(url)
        if "lastPrice" not in payload and "data" in payload and isinstance(payload["data"], dict):
            payload = payload["data"]
        return payload

    def fetch_intraday_candles(self, symbol: str, timeframe: int = 5, limit: int = 200) -> pd.DataFrame:
        """盤中僅抓最近 1~2 個時間窗的 intraday K 棒，不會抓 60 天歷史。"""
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{symbol}"
        params = {"timeframe": str(timeframe), "limit": str(limit)}
        payload = self._request_json(url, params=params)
        data = payload.get("data", payload.get("candles", []))
        df = pd.DataFrame(data)
        if df.empty:
            return df
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    @staticmethod
    def _sma(series: pd.Series, length: int) -> pd.Series:
        return series.rolling(window=length, min_periods=length).mean()

    @staticmethod
    def _ema(series: pd.Series, length: int) -> pd.Series:
        return series.ewm(span=length, adjust=False).mean()

    @staticmethod
    def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(window=length).mean()
        loss = (-delta.clip(upper=0)).rolling(window=length).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50.0)
        return rsi

    @staticmethod
    def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        fast_ema = series.ewm(span=fast, adjust=False).mean()
        slow_ema = series.ewm(span=slow, adjust=False).mean()
        macd = fast_ema - slow_ema
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        hist = macd - signal_line
        out = pd.DataFrame({
            "MACD_12_26_9": macd,
            "MACD": macd,
            "MACDs_12_26_9": signal_line,
            "MACDs": signal_line,
            "MACDh_12_26_9": hist,
            "MACDh": hist,
        })
        return out

    @staticmethod
    def _stoch(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3) -> pd.DataFrame:
        rolling_high = high.rolling(window=k, min_periods=k).max()
        rolling_low = low.rolling(window=k, min_periods=k).min()
        pct_k = ((close - rolling_low) / (rolling_high - rolling_low).replace(0, np.nan)) * 100
        pct_k = pct_k.fillna(50.0)
        pct_d = pct_k.ewm(span=d, adjust=False).mean()
        return pd.DataFrame({
            f"STOCHk_{k}_{d}": pct_k,
            f"STOCHd_{k}_{d}": pct_d,
            "STOCHk": pct_k,
            "STOCHd": pct_d,
        })

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(window=length, min_periods=length).mean()

    @staticmethod
    def _bbands(close: pd.Series, length: int = 20, std: float = 2.0) -> pd.DataFrame:
        ma = close.rolling(window=length, min_periods=length).mean()
        std_dev = close.rolling(window=length, min_periods=length).std(ddof=0)
        upper = ma + (std_dev * std)
        lower = ma - (std_dev * std)
        return pd.DataFrame({
            "BBANDS_upper": upper,
            "BBANDS_middle": ma,
            "BBANDS_lower": lower,
        })

    def add_technical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算全套盤中/盤後技術指標，且保證不需要額外網路請求。
        """
        df = self._normalize_ohlcv(df).copy()

        if df.empty:
            return df

        # 均線
        df["MA5"] = self._sma(df["close"], 5)
        df["MA10"] = self._sma(df["close"], 10)
        df["MA20"] = self._sma(df["close"], 20)
        df["MA60"] = self._sma(df["close"], 60)

        # EMA
        df["EMA12"] = self._ema(df["close"], 12)
        df["EMA26"] = self._ema(df["close"], 26)

        # RSI / MACD / KD
        df["RSI14"] = self._rsi(df["close"], 14)
        df["RSI6"] = self._rsi(df["close"], 6)

        macd = self._macd(df["close"], 12, 26, 9)
        for col in macd.columns:
            df[col] = macd[col]

        stoch = self._stoch(df["high"], df["low"], df["close"], 14, 3)
        for col in stoch.columns:
            df[col] = stoch[col]

        # 波動率與布林帶
        df["ATR14"] = self._atr(df["high"], df["low"], df["close"], 14)
        bb = self._bbands(df["close"], 20, 2)
        for col in bb.columns:
            df[col] = bb[col]

        # 成交量動能
        df["VOL_MA5"] = self._sma(df["volume"], 5)
        df["VOL_MA20"] = self._sma(df["volume"], 20)
        df["VOL_RATIO"] = df["volume"] / df["VOL_MA20"].replace(0, np.nan)

        # 壓力 / 支撐位：統計前 20 根 K 棒高低點
        df["壓力價_20"] = df["high"].rolling(window=20, min_periods=5).max().shift(1)
        df["支撐價_20"] = df["low"].rolling(window=20, min_periods=5).min().shift(1)
        df["壓力價_10"] = df["high"].rolling(window=10, min_periods=3).max().shift(1)
        df["支撐價_10"] = df["low"].rolling(window=10, min_periods=3).min().shift(1)

        # 3K / 5K 突破
        df["前3K最高位"] = df["high"].rolling(window=3, min_periods=3).max().shift(1)
        df["前5K最高位"] = df["high"].rolling(window=5, min_periods=5).max().shift(1)
        df["前3K最低位"] = df["low"].rolling(window=3, min_periods=3).min().shift(1)
        df["is_3k_breakout"] = (df["close"] > df["前3K最高位"]).fillna(False)
        df["is_5k_breakout"] = (df["close"] > df["前5K最高位"]).fillna(False)

        # 盤中 K 棒強弱判斷
        df["body_ratio"] = np.where(
            df["close"] > df["open"],
            (df["close"] - df["open"]) / np.maximum(df["high"] - df["low"], 1e-6),
            (df["open"] - df["close"]) / np.maximum(df["high"] - df["low"], 1e-6),
        )

        df["技術分數"] = 0.0
        df.loc[df["close"] > df["MA20"], "技術分數"] += 25
        df.loc[df["close"] > df["MA5"], "技術分數"] += 15
        df.loc[df["RSI14"] >= 50, "技術分數"] += 15
        df.loc[df["RSI14"] >= 70, "技術分數"] -= 10
        df.loc[df["is_3k_breakout"], "技術分數"] += 30
        df.loc[df["is_5k_breakout"], "技術分數"] += 20
        df.loc[df["VOL_RATIO"].fillna(0) > 1.5, "技術分數"] += 15
        df.loc[df["MACDh"].fillna(0) > 0, "技術分數"] += 10

        df["技術分數"] = df["技術分數"].clip(0, 100)
        return df

    def build_signal_snapshot(self, symbol: str, df: Optional[pd.DataFrame] = None) -> SignalResult:
        """根據最新 K 線狀態，產出單一股票的技術面快照。"""
        if df is None:
            df = self.cache.get(symbol)
        if df is None:
            raise ValueError(f"No cached historical data for symbol {symbol}. Call preload_symbols() first.")

        data = self.add_technical_features(df)
        latest = data.iloc[-1].copy()

        score = float(latest.get("技術分數", 0.0))
        rsi = float(latest.get("RSI14", 50.0))
        macd = float(latest.get("MACD_12_26_9", latest.get("MACD", 0.0)))
        signal = float(latest.get("MACDs_12_26_9", latest.get("MACDs", 0.0)))
        hist = float(latest.get("MACDh_12_26_9", latest.get("MACDh", 0.0)))

        result = SignalResult(
            {
                "symbol": symbol,
                "date": str(latest.get("date")),
                "close": float(latest.get("close", 0.0)),
                "open": float(latest.get("open", 0.0)),
                "high": float(latest.get("high", 0.0)),
                "low": float(latest.get("low", 0.0)),
                "volume": float(latest.get("volume", 0.0)),
                "ma5": float(latest.get("MA5", 0.0)),
                "ma10": float(latest.get("MA10", 0.0)),
                "ma20": float(latest.get("MA20", 0.0)),
                "ma60": float(latest.get("MA60", 0.0)),
                "rsi14": rsi,
                "rsi6": float(latest.get("RSI6", 0.0)),
                "macd": macd,
                "macd_signal": signal,
                "macd_hist": hist,
                "atr14": float(latest.get("ATR14", 0.0)),
                "pressure_20": float(latest.get("壓力價_20", 0.0)),
                "support_20": float(latest.get("支撐價_20", 0.0)),
                "is_3k_breakout": bool(latest.get("is_3k_breakout", False)),
                "is_5k_breakout": bool(latest.get("is_5k_breakout", False)),
                "volume_ratio": float(latest.get("VOL_RATIO", 0.0)),
                "score": score,
                "trend": self._score_to_trend(score, rsi, macd, hist),
            }
        )
        return result

    def _score_to_trend(self, score: float, rsi: float, macd: float, hist: float) -> str:
        if score >= 80:
            return "超強偏多"
        if score >= 65:
            return "偏多續強"
        if score >= 50:
            return "中性偏多"
        if score >= 35:
            return "震盪整理"
        if rsi > 70 and macd < 0:
            return "短線過熱"
        if hist < 0:
            return "弱勢整理"
        return "偏空"

    def preload_symbols(self, symbols: List[str], lookback_days: int = 60, timeframe: str = "D") -> Dict[str, pd.DataFrame]:
        """盤前批次載入：一次抓取每個股票的歷史日 K 線。"""
        loaded = {}
        for symbol in symbols:
            try:
                df = self.fetch_historical_candles(symbol, timeframe=timeframe, lookback_days=lookback_days)
                loaded[symbol] = self.add_technical_features(df)
            except Exception as exc:
                print(f"[warning] preload failed for {symbol}: {exc}")
        self.cache.update(loaded)
        return loaded

    def update_live_bar(self, symbol: str, live_price: float, high: Optional[float] = None, low: Optional[float] = None, volume: float = 0.0) -> Dict[str, Any]:
        """
        盤中增量更新：不重新抓歷史資料，只更新當前記憶體內的最新 K 棒（或即時 tick），用於毫秒級計算。
        """
        symbol = str(symbol).strip()
        if symbol not in self.live_history:
            self.live_history[symbol] = {
                "last_price": float(live_price),
                "high": float(high or live_price),
                "low": float(low or live_price),
                "close": float(live_price),
                "volume": float(volume),
                "updated_at": datetime.now(),
            }
        else:
            hist = self.live_history[symbol]
            hist["last_price"] = float(live_price)
            hist["close"] = float(live_price)
            hist["high"] = max(float(hist.get("high", live_price)), float(high or live_price or hist.get("high", live_price)))
            hist["low"] = min(float(hist.get("low", live_price)), float(low or live_price or hist.get("low", live_price)))
            hist["volume"] = float(hist.get("volume", 0.0)) + float(volume)
            hist["updated_at"] = datetime.now()

        if symbol not in self.cache:
            self.cache[symbol] = pd.DataFrame([
                {
                    "date": pd.Timestamp.now(tz="Asia/Taipei"),
                    "open": float(live_price),
                    "high": float(high or live_price),
                    "low": float(low or live_price),
                    "close": float(live_price),
                    "volume": float(volume),
                }
            ])
        else:
            last_row = self.cache[symbol].iloc[-1].copy()
            last_row["date"] = pd.Timestamp.now(tz="Asia/Taipei")
            last_row["high"] = max(float(last_row.get("high", live_price)), float(high or live_price or last_row.get("high", live_price)))
            last_row["low"] = min(float(last_row.get("low", live_price)), float(low or live_price or last_row.get("low", live_price)))
            last_row["close"] = float(live_price)
            last_row["volume"] = float(last_row.get("volume", 0.0)) + float(volume)
            self.cache[symbol] = pd.concat([self.cache[symbol], pd.DataFrame([last_row])], ignore_index=True)

        signal = self.build_signal_snapshot(symbol, self.cache[symbol])
        return dict(signal)

    def detect_breakout_candidates(self, symbols: List[str], min_score: float = 58.0) -> List[Dict[str, Any]]:
        """找出符合 3K/5K 突破 + 技術分數門檻的股票。"""
        candidates: List[Dict[str, Any]] = []
        for symbol in symbols:
            try:
                snapshot = self.build_signal_snapshot(symbol)
            except Exception:
                continue
            if snapshot.score >= min_score and (snapshot.is_3k_breakout or snapshot.is_5k_breakout):
                candidates.append(dict(snapshot))
        candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
        return candidates

    def evaluate_alert_triggers(
        self,
        symbol: str,
        snapshot: Optional[Dict[str, Any]] = None,
        chip: Optional[Dict[str, Any]] = None,
        insider: Optional[Dict[str, Any]] = None,
        effective_3k: Optional[Dict[str, Any]] = None,
        min_score: float = 60.0,
        min_volume_ratio: float = 2.5,
    ) -> Dict[str, Any]:
        """
        累積式觸發優先級：
        - Tier 1 (基礎): 量能 >= 2.5x + 技術分數 >= 60 + 日線多頭型態優 -> 發送
        - Tier 2 (進階): Tier1 + 內部人買超存在 -> 直接發送
        - Tier 3 (終極): Tier2 + 大戶買超 >= 400張 + 連買(3天+) -> 直接發送
        """
        if snapshot is None:
            snapshot = dict(self.build_signal_snapshot(symbol))

        chip = {
            "foreign": float(chip.get("foreign", 0.0) if chip else 0.0),
            "investment": float(chip.get("investment", 0.0) if chip else 0.0),
            "dealer": float(chip.get("dealer", 0.0) if chip else 0.0),
            "big_holder": float(chip.get("big_holder", 0.0) if chip else 0.0),
            "net_buy": float(chip.get("net_buy", 0.0) if chip else 0.0),
        }
        insider = {
            "net_buy": float(insider.get("net_buy", 0.0) if insider else 0.0),
            "buy_count": int(insider.get("buy_count", 0) if insider else 0),
            "buy_streak": int(insider.get("buy_streak", 0) if insider else 0),
            "annotation": str(insider.get("annotation", "買超") if insider else "買超"),
        }

        close_price = float(snapshot.get("close", 0.0))
        score = float(snapshot.get("score", 0.0))
        volume_ratio = float(snapshot.get("volume_ratio", 0.0))
        trend = snapshot.get("trend", "")
        is_3k_breakout = bool(snapshot.get("is_3k_breakout", False))
        is_5k_breakout = bool(snapshot.get("is_5k_breakout", False))
        ma5 = float(snapshot.get("ma5", 0.0))
        ma20 = float(snapshot.get("ma20", 0.0))
        rsi14 = float(snapshot.get("rsi14", 0.0))
        macd_hist = float(snapshot.get("macd_hist", 0.0))

        # Tier 1: 基礎條件 (量能 2.5x + 技術分數 >= 60 + 日線多頭型態優)
        volume_threshold = volume_ratio >= min_volume_ratio
        score_threshold = score >= min_score
        # 日線多頭型態優: 價格 > MA5 > MA20 OR 突破 OR RSI > 50 OR MACD > 0
        daily_bullish = (
            (ma5 > 0 and ma20 > 0 and close_price > ma5 > ma20) or
            is_3k_breakout or is_5k_breakout or
            (rsi14 > 50 and macd_hist > 0)
        )
        tier1_base = volume_threshold and score_threshold and daily_bullish
        three_k_confirmed = effective_3k is not None
        if three_k_confirmed:
            tier1_base = tier1_base and bool(effective_3k)

        # Tier 2: 進階 (Tier1 + 內部人買超)
        tier1_insider = insider.get("net_buy", 0.0) > 0
        tier2_advanced = tier1_base and tier1_insider

        # Tier 3: 終極 (Tier2 + 大戶買超 >= 400張 + 連買 >= 3天)
        big_holder_shares = float(chip.get("big_holder", 0.0))
        is_consecutive_buy = insider.get("buy_streak", 0) >= 3  # 3天連買
        tier3_ultimate = tier2_advanced and big_holder_shares >= 400.0 and is_consecutive_buy

        # 優先級判斷 (從高到低)
        tier_level = 0
        should_send = False
        trigger_reason = ""

        if tier3_ultimate:
            should_send = True
            tier_level = 3
            trigger_reason = f"量能{volume_ratio:.2f}x + 技術{score:.1f} + 內部人連買 + 大戶{big_holder_shares:.0f}張"
        elif tier2_advanced:
            should_send = True
            tier_level = 2
            trigger_reason = f"量能{volume_ratio:.2f}x + 技術{score:.1f} + 內部人買超"
        elif tier1_base:
            should_send = True
            tier_level = 1
            trigger_reason = f"量能{volume_ratio:.2f}x + 技術{score:.1f}"
        else:
            should_send = False
            tier_level = 0
            trigger_reason = "未符合任何觸發條件"

        if insider["buy_streak"] >= 3:
            annotation = "連三買"
        elif insider["buy_count"] >= 2:
            annotation = "連買"
        elif insider["net_buy"] > 0:
            annotation = "買超"
        else:
            annotation = insider["annotation"] or "買超"

        return {
            "symbol": symbol,
            "should_send": bool(should_send),
            "trigger_reason": trigger_reason,
            "tier_level": int(tier_level),
            "tier1_base": bool(tier1_base),
            "tier1_insider": bool(tier1_insider),
            "tier2_advanced": bool(tier2_advanced),
            "tier3_ultimate": bool(tier3_ultimate),
            "effective_3k": effective_3k,
            "three_k_confirmed": three_k_confirmed,
            "is_consecutive_buy": bool(is_consecutive_buy),
            "volume_ratio": volume_ratio,
            "score": score,
            "annotation": annotation,
            "chip": chip,
            "insider": insider,
            "snapshot": snapshot,
            "reason": [
                f"Tier1基礎: 量能{volume_ratio:.2f}x + 技術{score:.1f}" if tier1_base else "未達量能或技術門檻",
                f"Tier2進階: 內部人買超{insider.get('net_buy', 0):.0f}" if tier1_insider else "無內部人買超",
                f"Tier3終極: 大戶{big_holder_shares:.0f}張 + 連買{insider.get('buy_streak', 0)}天" if is_consecutive_buy else f"無連買記錄",
            ],
        }

    def build_trigger_message(
        self,
        symbol: str,
        snapshot: Optional[Dict[str, Any]] = None,
        chip: Optional[Dict[str, Any]] = None,
        insider: Optional[Dict[str, Any]] = None,
        effective_3k: Optional[Dict[str, Any]] = None,
    ) -> str:
        """組合 Telegram 主動通知格式，展示累積式優先級觸發原因 + nstock 超連結。"""
        decision = self.evaluate_alert_triggers(
            symbol,
            snapshot=snapshot,
            chip=chip,
            insider=insider,
            effective_3k=effective_3k,
        )
        if decision["snapshot"] is None:
            decision["snapshot"] = {}
        snap = decision["snapshot"]
        chip_data = decision["chip"]
        insider_data = decision["insider"]
        annotation = decision["annotation"]
        trigger_reason = decision.get("trigger_reason", "")
        tier_level = decision.get("tier_level", 0)

        tier_markers = {
            0: "",
            1: "🟡 Tier 1 基礎觸發 (量能+技術)",
            2: "🟠 Tier 2 進階觸發 (加內部人買超)",
            3: "🔴 Tier 3 終極觸發 (加大戶+連買)",
        }
        tier_marker = tier_markers.get(tier_level, "")
        
        # nstock 超連結
        nstock_url = f"https://www.nstock.tw/stock_info?stock_id={symbol}"

        return (
            f"*{tier_marker}*\n"
            f"📈 *標的：* [{symbol}]({nstock_url})\n"
            f"💰 價格: {float(snap.get('close', 0.0)):.2f}\n"
            f"🎯 觸發原因: {trigger_reason}\n"
            f"─────────\n"
            f"📊 技術面:\n"
            f"  RSI14: {float(snap.get('rsi14', 0.0)):.1f}\n"
            f"  技術分數: {float(snap.get('score', 0.0)):.1f}\n"
            f"  趨勢: {snap.get('trend', 'N/A')}\n"
            f"  突破: 3K={snap.get('is_3k_breakout', False)}, 5K={snap.get('is_5k_breakout', False)}\n"
            f"  量能比: {float(snap.get('volume_ratio', 0.0)):.2f}x\n"
            f"  有效3K: 收盤 {float(effective_3k['close']):.2f} > 前兩K高點 {float(effective_3k['breakout_price']):.2f}, "
            f"K3量比 {float(effective_3k['volume_ratio']):.2f}x\n" if effective_3k else ""
            f"─────────\n"
            f"💼 籌碼面:\n"
            f"  內部買超: {insider_data.get('net_buy', 0.0):.0f} ({annotation})\n"
            f"  大戶融資: {chip_data.get('big_holder', 0.0):.0f}\n"
            f"  外資: {chip_data.get('foreign', 0.0):.0f}\n"
            f"  投信: {chip_data.get('investment', 0.0):.0f}\n"
            f"  自營: {chip_data.get('dealer', 0.0):.0f}\n"
            f"═════════════════════"
        )

    def send_signal_alert(
        self,
        symbol: str,
        snapshot: Optional[Dict[str, Any]] = None,
        chip: Optional[Dict[str, Any]] = None,
        insider: Optional[Dict[str, Any]] = None,
        effective_3k: Optional[Dict[str, Any]] = None,
        chat_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Only send Telegram when the trigger conditions are satisfied."""
        if snapshot is None:
            snapshot = dict(self.build_signal_snapshot(symbol))

        if effective_3k is None:
            return {
                "status_code": 200,
                "body": {"ok": False, "reason": "effective_3k_required"},
            }

        decision = self.evaluate_alert_triggers(
            symbol,
            snapshot=snapshot,
            chip=chip,
            insider=insider,
            effective_3k=effective_3k,
        )
        if not decision["should_send"]:
            return {
                "status_code": 200,
                "body": {"ok": False, "reason": "trigger_not_met", "decision": decision},
            }

        msg = self.build_trigger_message(
            symbol,
            snapshot=snapshot,
            chip=chip,
            insider=insider,
            effective_3k=effective_3k,
        )
        return send_telegram_message(msg, chat_id=chat_id, token=TELEGRAM_BOT_TOKEN)


class WarrantReverseMonitor:
    """
    以「現股急拉 + 外盤大單」逆向監控權證熱度，持續維持免費版核心思路：
    不監控 20,000 檔權證，而是監控 400~500 檔現股，當現股爆量敲外盤與急拉時，反查對應權證。
    """

    def __init__(self, quota: int = 30, group_size: int = 20):
        self.quota = quota
        self.group_size = group_size
        self.last_snapshot: Dict[str, Dict[str, float]] = {}
        self.last_pool_metadata: Dict[str, Dict[str, Any]] = {}
        self.latest_quotes: Dict[str, Dict[str, Any]] = {}

    def fetch_hot_warrant_underlyings(self, quota: Optional[int] = None) -> List[str]:
        """
        參考 test_catchWarrant.py：從富邦權證成交量榜彙總認購/認售量，
        過濾到期日、價外幅度與認購認售比後，映射回前 quota 檔現股。
        """
        limit = quota or self.quota
        min_days_to_expiry = 30
        max_otm_percent = 30
        min_call_put_ratio = 1.5
        target_stocks: Dict[str, Dict[str, Any]] = {}

        try:
            for callput in ("C", "P"):
                page = 1
                total_pages = 1
                while page <= total_pages:
                    response = requests.get(
                        FUBON_RANK_URL,
                        params={"rank": "sumvol_desc", "callput": callput, "page": page},
                        headers=FUBON_RANK_HEADERS,
                        timeout=20,
                    )
                    response.raise_for_status()
                    if page == 1:
                        page_match = re.search(r"totPage:'(\d+)'", response.text)
                        total_pages = int(page_match.group(1)) if page_match else 1

                    for record in re.findall(r"\{([^{}]+)\}", response.text):
                        fields: Dict[str, str] = {}
                        for field_name in ("ulcode", "ulsname", "idx_cp", "days", "iom", "sumvol"):
                            field_match = re.search(
                                rf"\b{field_name}:\s*(?:'([^']*)'|([^,}}]+))",
                                record,
                            )
                            if field_match:
                                fields[field_name] = (
                                    field_match.group(1)
                                    if field_match.group(1) is not None
                                    else field_match.group(2).strip()
                                )

                        stock_code = fields.get("ulcode", "")
                        if not re.fullmatch(r"\d{4}", stock_code):
                            continue
                        days = int(_safe_cast(fields.get("days"), float, 0))
                        moneyness = _safe_cast(fields.get("iom"), float, 0.0)
                        volume = int(_safe_cast(fields.get("sumvol"), float, 0))
                        if days < min_days_to_expiry or moneyness < -max_otm_percent:
                            continue

                        stock = target_stocks.setdefault(
                            stock_code,
                            {
                                "name": "".join(fields.get("ulsname", "").split()),
                                "price": fields.get("idx_cp", "-"),
                                "call_volume": 0,
                                "put_volume": 0,
                            },
                        )
                        stock["call_volume" if callput == "C" else "put_volume"] += volume
                    page += 1
        except (requests.RequestException, ValueError, TypeError) as exc:
            print(f"[富邦權證池] 取得失敗: {exc}")
            return []

        for stock_code in list(target_stocks):
            stock = target_stocks[stock_code]
            call_volume = stock["call_volume"]
            put_volume = stock["put_volume"]
            ratio = call_volume / put_volume if put_volume > 0 else float("inf")
            if call_volume == 0 or ratio < min_call_put_ratio:
                del target_stocks[stock_code]
                continue
            stock["call_put_ratio"] = ratio

        ranked = sorted(
            target_stocks.items(),
            key=lambda item: (item[1]["call_volume"], item[1]["put_volume"]),
            reverse=True,
        )
        self.last_pool_metadata = dict(ranked[:limit])
        return [stock_code for stock_code, _ in ranked[:limit]]

    def build_stock_groups(self, symbols: List[str]) -> List[List[str]]:
        groups = []
        for i in range(0, len(symbols), self.group_size):
            groups.append(symbols[i : i + self.group_size])
        return groups

    def _scan_group(self, group: List[str]) -> List[Dict[str, Any]]:
        """MIS 快照：每組 20 檔，針對 5 秒內成交量暴增與急拉判斷可能的避險訊號。"""
        if not group:
            return []

        valid_symbols = [sid for sid in group if re.fullmatch(r"\d{4}", sid)]
        ex_ch = "|".join(
            f"{exchange}_{sid}.tw"
            for sid in valid_symbols
            for exchange in ("tse", "otc")
        )
        if not ex_ch:
            return []

        try:
            res = requests.get(f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}", timeout=3)
            payload = res.json()
            rows = payload.get("msgArray", [])
        except Exception:
            return []

        triggered: List[Dict[str, Any]] = []
        for stock in rows:
            sid = str(stock.get("c", "")).strip()
            if not sid:
                continue
            current_price = _safe_cast(stock.get("z"), float, 0.0)
            reference_price = _safe_cast(stock.get("y"), float, 0.0)
            if current_price <= 0:
                current_price = reference_price
            total_vol = int(_safe_cast(stock.get("v"), float, 0.0))
            ask_values = str(stock.get("a", "")).split("_")
            ask_price_1 = _safe_cast(ask_values[0] if ask_values else None, float, 0.0)
            if current_price <= 0:
                continue
            self.latest_quotes[sid] = {
                "name": str(stock.get("n", "")).strip(),
                "current_price": current_price,
                "total_volume": total_vol,
            }
            prev = self.last_snapshot.get(sid)
            if prev is not None:
                prev_vol = float(prev.get("vol", 0.0))
                prev_price = float(prev.get("price", 0.0))
                diff_vol = total_vol - prev_vol
                diff_amount = diff_vol * current_price * 1000
                if diff_vol > 0 and diff_amount >= 3_000_000 and current_price >= prev_price:
                    triggered.append(
                        {
                            "sid": sid,
                            "name": stock.get("n", ""),
                            "current_price": current_price,
                            "diff_vol": diff_vol,
                            "diff_amount": diff_amount,
                            "ask_price_1": ask_price_1,
                            "total_vol": total_vol,
                        }
                    )
            self.last_snapshot[sid] = {"vol": float(total_vol), "price": float(current_price)}
        return triggered

    def scan_mis_for_warrant_hedge(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """整批掃描現股，找出符合外盤大單消耗 + 急拉的標的，供權證重點參考。"""
        self.latest_quotes = {}
        results: List[Dict[str, Any]] = []
        for group in self.build_stock_groups(symbols):
            for hit in self._scan_group(group):
                results.append(hit)
        results.sort(key=lambda item: item["diff_amount"], reverse=True)
        return results


class WarrantTelegramAlertRunner:
    """
    真正可用版：
    1) 產生 30 檔熱門現股池
    2) 用 MIS 逆向掃描現股急拉與大單消耗
    3) 反查對應權證熱點
    4) 合併技術指標 + 籌碼 + 內部買超
    5) 符合條件才直接發 Telegram 主動通知
    """

    def __init__(self, quota: int = 30, group_size: int = 20, chat_id: Optional[str] = None):
        self.quota = quota
        self.group_size = group_size
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.monitor = WarrantReverseMonitor(quota=quota, group_size=group_size)
        self.engine = TechnicalSignalEngine(api_key=FUGLE_API_KEY)
        self.chip_layer = FundamentalChipDataLayer()
        self.warrant_pool_metadata: Dict[str, Dict[str, Any]] = {}
        self.sent_signals: set[str] = set()
        self.last_effective_3k: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _fallback_underlyings() -> List[str]:
        return [
            "2330", "2454", "2317", "3008", "2881", "2383", "2379", "2303", "2891", "6505",
            "4938", "3034", "2412", "2882", "3231", "2368", "2357", "2474", "3494", "2449",
            "3711", "3661", "3105", "3103", "2880", "2884", "3090", "2408", "2347", "2345",
        ]

    def build_hot_underlying_pool(self, custom_symbols: Optional[List[str]] = None) -> List[str]:
        if custom_symbols:
            return [str(symbol).strip() for symbol in custom_symbols if re.fullmatch(r"\d{4}", str(symbol).strip())]

        pool = self.monitor.fetch_hot_warrant_underlyings(self.quota)
        if not pool:
            return list(self.warrant_pool_metadata)

        previous_pool = self.warrant_pool_metadata
        current_pool = self.monitor.last_pool_metadata
        for symbol, stock in current_pool.items():
            previous_volume = int(previous_pool.get(symbol, {}).get("call_volume", 0))
            current_volume = int(stock.get("call_volume", 0))
            volume_change = current_volume - previous_volume
            growth_percent = volume_change / previous_volume * 100 if previous_volume > 0 else 0.0
            stock["warrant_volume_change"] = volume_change
            stock["warrant_volume_growth_percent"] = growth_percent
            stock["is_warrant_volume_accelerating"] = (
                previous_volume > 0
                and volume_change >= WARRANT_VOLUME_GROWTH_MINIMUM
                and growth_percent >= WARRANT_VOLUME_GROWTH_PERCENT
            )
        self.warrant_pool_metadata = current_pool
        return pool

    def build_startup_status_message(self, pool: Optional[List[str]] = None) -> str:
        """建立啟動LOG/測試通知，列出熱門池前五檔與現價。"""
        symbols = pool if pool is not None else self.build_hot_underlying_pool()
        top_symbols = symbols[:5]

        lines = [
            "【啟動測試】權證現股監控系統",
            f"啟動時間: {get_taipei_now():%Y-%m-%d %H:%M:%S}",
            f"監控池檔數: {len(symbols)}",
            "熱門池前五檔:",
        ]
        if not top_symbols:
            lines.append("  無法取得熱門權證池資料")
            return "\n".join(lines)

        for index, symbol in enumerate(top_symbols, start=1):
            info = self.warrant_pool_metadata.get(symbol, {})
            price = info.get("price", "--")
            lines.append(
                f"{index}. {symbol} {info.get('name', '--')}"
                f"｜價格 {price}"
            )
        return "\n".join(lines)

    def send_startup_test_notification(self, pool: Optional[List[str]] = None) -> Dict[str, Any]:
        """每次啟動發送一次池資料測試通知，不代表交易訊號。"""
        message = self.build_startup_status_message(pool)
        print(message)
        try:
            return send_telegram_message(message, chat_id=self.chat_id, token=TELEGRAM_BOT_TOKEN)
        except (requests.RequestException, ValueError) as exc:
            print(f"[啟動測試通知] 發送失敗: {exc}")
            return {"status_code": 0, "body": {"ok": False, "error": str(exc)}}

    def log_monitoring_status(self, pool: Optional[List[str]] = None) -> None:
        """依 scanner.py 風格輸出本輪30檔批次行情與3K狀態。"""
        symbols = pool if pool is not None else list(self.warrant_pool_metadata)
        quotes = self.monitor.latest_quotes
        print(f"[監控LOG {get_taipei_now():%Y-%m-%d %H:%M:%S}] 池子 {len(symbols)} 檔", flush=True)
        print("股號     股名                 現價         3K突破價", flush=True)
        for symbol in symbols:
            info = self.warrant_pool_metadata.get(symbol, {})
            quote = quotes.get(symbol, {})
            current_price = quote.get("current_price", "--")
            effective_3k = self.last_effective_3k.get(symbol)
            breakout_price = (
                f"{float(effective_3k['breakout_price']):.2f}"
                if effective_3k else "--"
            )
            print(
                f"{symbol:<8}"
                f"{str(quote.get('name') or info.get('name') or '--')[:18]:<20}"
                f"{str(current_price):>10}"
                f"{breakout_price:>14}"
                , flush=True
            )

    def refresh_monitoring_status(self, pool: Optional[List[str]] = None) -> None:
        """非盤中也刷新行情與3K狀態，但不執行交易訊號或Telegram通知。"""
        symbols = pool if pool is not None else list(self.warrant_pool_metadata)
        try:
            self.monitor.scan_mis_for_warrant_hedge(symbols)
        except Exception as exc:
            print(f"[監控LOG] MIS快照更新失敗: {exc}", flush=True)

        try:
            self.last_effective_3k = fetch_effective_3k_breakouts(symbols)
        except Exception as exc:
            print(f"[監控LOG] 5分K更新失敗: {exc}", flush=True)
            self.last_effective_3k = {}
        self.log_monitoring_status(symbols)

    def _fetch_real_chip_signal(
        self,
        symbol: str,
        insider: Optional[Dict[str, Dict[str, Any]]] = None,
        three_inst: Optional[Dict[str, Dict[str, Any]]] = None,
        margin: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """回傳指定現股的真實籌碼資料，不以急拉金額推估籌碼。"""
        try:
            insider = insider if insider is not None else FundamentalChipDataLayer.fetch_insider_buy_data(lookback_days=30)
            three_inst = three_inst if three_inst is not None else FundamentalChipDataLayer.fetch_three_institutional_buy(lookback_days=30)
            margin = margin if margin is not None else FundamentalChipDataLayer.fetch_margin_buy(lookback_days=30)
        except Exception:
            return {}

        symbol = str(symbol).strip()
        result = {
            "foreign": 0.0,
            "investment": 0.0,
            "dealer": 0.0,
            "big_holder": 0.0,
            "net_buy": 0.0,
            "insider_net_buy": 0.0,
            "insider_buy_count": 0,
            "insider_buy_streak": 0,
            "insider_names": [],
            "source": "",
        }

        insider_data = insider.get(symbol, {})
        institutional_data = three_inst.get(symbol, {})
        margin_data = margin.get(symbol, {})
        result["insider_net_buy"] = float(insider_data.get("net_buy", 0.0))
        result["insider_buy_count"] = int(insider_data.get("buy_count", 0))
        result["insider_buy_streak"] = int(insider_data.get("buy_streak", 0))
        result["insider_names"] = insider_data.get("buy_names", [])
        result["foreign"] = float(institutional_data.get("foreign", 0.0))
        result["investment"] = float(institutional_data.get("investment", 0.0))
        result["dealer"] = float(institutional_data.get("dealer", 0.0))
        result["net_buy"] = float(institutional_data.get("net_buy", 0.0))
        result["big_holder"] = float(margin_data.get("net_buy", 0.0))
        sources = []
        if insider_data.get("net_buy", 0.0) > 0:
            sources.append(f"內部人買超({len(insider_data.get('buy_names', []))}位)")
        if institutional_data.get("net_buy", 0.0) > 0:
            sources.append("三大法人")
        if margin_data.get("net_buy", 0.0) > 0:
            sources.append("融資")
        result["source"] = "+".join(sources)

        return result

    def _safe_snapshot(self, symbol: str, hit: Dict[str, Any]) -> Dict[str, Any]:
        if symbol not in self.engine.cache:
            self.engine.fetch_historical_candles(symbol, timeframe="D", lookback_days=60)
        daily_df = self.engine.cache[symbol]
        signal = dict(self.engine.build_signal_snapshot(symbol, daily_df))
        last_price = _safe_cast(hit.get("current_price"), float, 0.0)
        total_volume = _safe_cast(hit.get("total_vol"), float, 0.0)
        if last_price <= 0 or total_volume <= 0:
            raise ValueError(f"MIS 即時資料不完整: {symbol}")
        signal.update({
            "close": last_price,
            "volume": total_volume,
            "date": str(get_taipei_now()),
        })
        return signal

    def run_cycle(self, custom_symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """執行一輪現股逆向掃描並主動發送 Telegram，返回所有觸發訊號。優先使用真實的內部人 + 法人買超資料。"""
        self.last_effective_3k = {}
        pool = self.build_hot_underlying_pool(custom_symbols)
        hits = self.monitor.scan_mis_for_warrant_hedge(pool)
        if not hits:
            return []

        symbols = [str(hit.get("sid", "")).strip() for hit in hits[:10]]
        volume_multiplier = (
            OPENING_KLINE_VOLUME_MULTIPLIER
            if is_opening_noise_period()
            else KLINE_VOLUME_MULTIPLIER
        )
        effective_3k_by_symbol = fetch_effective_3k_breakouts(symbols, volume_multiplier)
        self.last_effective_3k = effective_3k_by_symbol
        try:
            insider_data = FundamentalChipDataLayer.fetch_insider_buy_data(lookback_days=30)
            institutional_data = FundamentalChipDataLayer.fetch_three_institutional_buy(lookback_days=30)
            margin_data = FundamentalChipDataLayer.fetch_margin_buy(lookback_days=30)
        except Exception as exc:
            print(f"[籌碼資料] 本輪取得失敗: {exc}")
            return []

        alerts: List[Dict[str, Any]] = []
        for hit in hits[:10]:
            symbol = str(hit.get("sid", "")).strip()
            if not symbol:
                continue

            effective_3k = effective_3k_by_symbol.get(symbol)
            if not effective_3k:
                continue
            signal_key = f"{symbol}:{effective_3k['bar_time']}"
            if signal_key in self.sent_signals:
                continue

            try:
                snapshot = self._safe_snapshot(symbol, hit)
            except (requests.RequestException, ValueError, TypeError) as exc:
                print(f"[即時快照] {symbol} 取得失敗: {exc}")
                continue
            snapshot["effective_3k"] = effective_3k
            snapshot["is_3k_breakout"] = True
            snapshot["volume_ratio"] = max(
                float(snapshot.get("volume_ratio", 0.0)),
                float(effective_3k.get("volume_ratio", 0.0)),
            )
            try:
                real_chip = self._fetch_real_chip_signal(
                    symbol,
                    insider=insider_data,
                    three_inst=institutional_data,
                    margin=margin_data,
                )
            except Exception as exc:
                print(f"[籌碼資料] {symbol} 取得失敗: {exc}")
                continue
            chip = real_chip
            insider = {
                "net_buy": real_chip.get("insider_net_buy", 0.0),
                "buy_count": real_chip.get("insider_buy_count", 0),
                "buy_streak": real_chip.get("insider_buy_streak", 0),
                "annotation": "買超" if real_chip.get("insider_net_buy", 0.0) > 0 else "無買超",
            }
            decision = self.engine.evaluate_alert_triggers(
                symbol,
                snapshot=snapshot,
                chip=chip,
                insider=insider,
                effective_3k=effective_3k,
            )
            if not decision["should_send"]:
                continue

            message = self.engine.build_trigger_message(
                symbol,
                snapshot=snapshot,
                chip=chip,
                insider=insider,
                effective_3k=effective_3k,
            )
            source_info = real_chip.get("source", "無買超資料")
            warrant_info = self.warrant_pool_metadata.get(symbol, {})
            warrant_grade = "AA" if warrant_info.get("is_warrant_volume_accelerating") else "A"
            message += (
                f"\n反查標的: {symbol}"
                f"\nMIS急拉量: {float(hit.get('diff_amount', 0.0)):.0f}"
                f"\n先行價差: {float(hit.get('current_price', 0.0)):.2f}"
                f"\n權證評級: {warrant_grade}"
                f"\n認購量增: {int(warrant_info.get('warrant_volume_change', 0)):+,}"
                f" ({float(warrant_info.get('warrant_volume_growth_percent', 0.0)):+.1f}%)"
                f"\n籌碼來源: {source_info}"
            )
            payload = send_telegram_message(message, chat_id=self.chat_id, token=TELEGRAM_BOT_TOKEN)
            if payload.get("body", {}).get("ok"):
                self.sent_signals.add(signal_key)
            alerts.append({
                "symbol": symbol,
                "hit": hit,
                "signal_key": signal_key,
                "warrant_grade": warrant_grade,
                "warrant_volume_change": warrant_info.get("warrant_volume_change", 0),
                "warrant_volume_growth_percent": warrant_info.get("warrant_volume_growth_percent", 0.0),
                "chip_source": source_info,
                "real_chip": real_chip,
                "decision": decision,
                "telegram": payload,
            })
        return alerts


def example_usage():
    """示例：盤前載入 + 即時更新。"""
    engine = TechnicalSignalEngine(api_key=FUGLE_API_KEY)

    symbols = ["2330", "2317", "2454"]
    data = engine.preload_symbols(symbols, lookback_days=90)
    print("[盤前預算完成]", {k: list(v.columns) for k, v in data.items()})

    for symbol in symbols:
        snapshot = engine.build_signal_snapshot(symbol)
        print(json.dumps({
            "symbol": symbol,
            "score": snapshot["score"],
            "trend": snapshot["trend"],
            "rsi14": snapshot["rsi14"],
            "is_3k_breakout": snapshot["is_3k_breakout"],
            "price": snapshot["close"],
        }, ensure_ascii=False, indent=2))

    # 盤中增量更新：不重新抓歷史資料，只在記憶體更新價格
    engine.update_live_bar("2330", live_price=905.0, high=910.0, low=900.0, volume=15000)
    engine.update_live_bar("2330", live_price=912.0, high=915.0, low=908.0, volume=22000)
    print(json.dumps(engine.build_signal_snapshot("2330"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # 定時執行 loop：每 10 秒掃一次盤中現股急拉信號
    # 支援每天 09:00 ~ 13:30 盤中自動監控

    runner = WarrantTelegramAlertRunner(quota=30, group_size=20, chat_id=TELEGRAM_CHAT_ID)
    
    print("=" * 60)
    print("🚀 權證現股即時逆向監控啟動")
    print("=" * 60)
    print(f"📊 Telegram 通知地址: {runner.chat_id}")
    print(f"💰 FinMind Token: 已設置" if FINMIND_TOKEN else "⚠️ FinMind Token: 未設置")
    print(f"🔑 Fugle API: 已設置" if FUGLE_API_KEY else "⚠️ Fugle API: 未設置")
    print("=" * 60)
    print()

    try:
        pool = runner.build_hot_underlying_pool()
    except Exception as exc:
        print(f"[啟動] 熱門權證池取得失敗: {exc}", flush=True)
        pool = []
    try:
        runner.monitor.scan_mis_for_warrant_hedge(pool)
    except Exception as exc:
        print(f"[啟動] MIS快照取得失敗: {exc}", flush=True)
    try:
        runner.last_effective_3k = fetch_effective_3k_breakouts(pool)
    except Exception as exc:
        print(f"[啟動] 5分K取得失敗: {exc}", flush=True)
        runner.last_effective_3k = {}
    runner.log_monitoring_status(pool)
    try:
        startup_result = runner.send_startup_test_notification(pool)
    except Exception as exc:
        print(f"[啟動測試通知] 發送失敗: {exc}", flush=True)
        startup_result = {"body": {"ok": False}}
    print(f"[啟動測試通知] Telegram ok={startup_result.get('body', {}).get('ok', False)}")

    cycle_count = 0
    last_pool_refresh = time.time()
    monitor_stop_at = get_monitor_stop_at()
    last_wait_log = 0.0
    print(f"[監控狀態] 已啟動，預計停止時間: {monitor_stop_at:%Y-%m-%d %H:%M:%S}")
    
    try:
        while True:
            cycle_count += 1
            now = get_taipei_now()

            if now >= monitor_stop_at:
                print(f"\n⏰ [{now:%Y-%m-%d %H:%M:%S}] 已到監控停止時間，監控停止")
                break

            if not is_market_hours(now):
                print(
                    f"\n⏳ [{now:%Y-%m-%d %H:%M:%S}] 監控持續運作，等待盤中"
                    f" (掃描時段: 09:00-13:30，停止: {monitor_stop_at:%H:%M:%S})",
                    flush=True,
                )
                runner.refresh_monitoring_status(pool)
                time.sleep(10)
                continue

            print(f"\n🔄 [週期 #{cycle_count}] {now:%Y-%m-%d %H:%M:%S}")
            
            # 每 5 分鐘刷新一次現股池（防止市場變化導致池子過舊）
            if time.time() - last_pool_refresh > 300:
                print("  📊 刷新熱門現股池...")
                pool = runner.build_hot_underlying_pool()
                last_pool_refresh = time.time()
                print(f"  ✅ 現股池更新: {len(pool)} 檔 {pool[:5]}...")
            
            if pool is None:
                pool = runner.build_hot_underlying_pool()
            
            # 執行一輪 MIS 逆向掃描
            try:
                alerts = runner.run_cycle(pool)
                if alerts:
                    print(f"  🎯 命中 {len(alerts)} 筆觸發信號!")
                    for alert in alerts:
                        sid = alert.get("symbol", "?")
                        chip_src = alert.get("chip_source", "未知")
                        tier = alert["decision"].get("tier_level", 0)
                        print(f"     - {sid} (Tier {tier}, 籌碼源: {chip_src})")
                else:
                    print("  ❌ 無符合條件的觸發信號")
            except Exception as e:
                print(f"  ⚠️  掃描異常: {e}")
            finally:
                runner.log_monitoring_status(pool)
            
            # 等待 10 秒後進行下一輪掃描
            print("  ⏳ 等待 10 秒...")
            time.sleep(10)
    
    except KeyboardInterrupt:
        print("\n\n📍 使用者停止監控")
    except Exception as e:
        print(f"\n❌ 致命錯誤: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("=" * 60)
        print("✅ 監控已停止")
        print("=" * 60)

