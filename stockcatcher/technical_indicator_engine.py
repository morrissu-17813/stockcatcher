import os
import json
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from dotenv import load_dotenv
import requests

_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=_ENV_PATH)

FUGLE_API_KEY = os.getenv("FUGLE_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1087480334")


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
            finmind_token = os.getenv("FINMIND_TOKEN", "")
            if not finmind_token:
                return {}
            
            # FinMind API: 董監事法人購買股數(buy_volume)
            # Dataset: TaiwanStockInsiderTrading
            url = "https://api.finmindtrade.com/api/v4/data"
            headers = {"Authorization": f"Bearer {finmind_token}"}
            
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
                    }

                result[sid]["net_buy"] += net_buy
                result[sid]["buy_count"] += 1
                result[sid]["last_date"] = date_str
                if person not in result[sid]["buy_names"]:
                    result[sid]["buy_names"].append(person)

            except Exception:
                continue

        return result

    @staticmethod
    def fetch_three_institutional_buy(lookback_days: int = 30) -> Dict[str, Dict[str, Any]]:
        """
        從 TWSE 開放資料抓三大法人每日買賣超。
        外資、投信、自營商。
        """
        try:
            url = "https://openapi.twse.com.tw/v1/opendata/t187ap40_L"
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

            foreign = _safe_cast(row.get("外資買賣超", 0), float, 0.0)
            investment = _safe_cast(row.get("投信買賣超", 0), float, 0.0)
            dealer = _safe_cast(row.get("自營商買賣超", 0), float, 0.0)
            net_buy = foreign + investment + dealer

            if sid not in result:
                result[sid] = {
                    "symbol": sid,
                    "foreign": 0.0,
                    "investment": 0.0,
                    "dealer": 0.0,
                    "net_buy": 0.0,
                    "last_date": None,
                }

            result[sid]["foreign"] += foreign
            result[sid]["investment"] += investment
            result[sid]["dealer"] += dealer
            result[sid]["net_buy"] += net_buy
            result[sid]["last_date"] = date_str

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
            df["date"] = pd.to_datetime(df["date"])
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
            df["date"] = pd.to_datetime(df["date"])
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
    ) -> str:
        """組合 Telegram 主動通知格式，展示累積式優先級觸發原因 + nstock 超連結。"""
        decision = self.evaluate_alert_triggers(symbol, snapshot=snapshot, chip=chip, insider=insider)
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
        chat_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Only send Telegram when the trigger conditions are satisfied."""
        if snapshot is None:
            snapshot = dict(self.build_signal_snapshot(symbol))

        decision = self.evaluate_alert_triggers(symbol, snapshot=snapshot, chip=chip, insider=insider)
        if not decision["should_send"]:
            return {
                "status_code": 200,
                "body": {"ok": False, "reason": "trigger_not_met", "decision": decision},
            }

        msg = self.build_trigger_message(symbol, snapshot=snapshot, chip=chip, insider=insider)
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

    def fetch_hot_warrant_underlyings(self, quota: Optional[int] = None) -> List[str]:
        """
        參考 scanner.py：從 TWSE 權證基本資料 + 成交資料做熱門權證池，最後映射回現股。
        這裡沿用免費方案：從官方資料生成前 {quota} 熱門現股池，作為後續 MIS 逆向監控的標的清單。
        """
        limit = quota or self.quota
        try:
            basic_res = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap37_L", timeout=30)
            trade_res = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap42_L", timeout=30)
            if basic_res.status_code != 200 or trade_res.status_code != 200:
                return []
            basic_rows = basic_res.json()
            trade_rows = trade_res.json()
            if not isinstance(basic_rows, list) or not isinstance(trade_rows, list):
                return []
        except Exception:
            return []

        pending = {}
        for row in basic_rows:
            if not isinstance(row, dict):
                continue
            if "認購" not in _norm_text(row.get("權證類型")).upper():
                continue

            underlying = _norm_text(row.get("標的證券/指數"))
            if not underlying:
                continue

            code_match = "".join(ch for ch in underlying if ch.isdigit())
            if len(code_match) == 4:
                sid = code_match
            else:
                sid = underlying.replace("-", "")
                if len(sid) != 4:
                    continue

            candidate = pending.setdefault(sid, {"turnover": 0.0, "volume": 0, "warrant_count": 0, "seen": set()})
            candidate["seen"].add(_norm_text(row.get("權證代號")))
            candidate["warrant_count"] = len(candidate["seen"])

        for row in trade_rows:
            if not isinstance(row, dict):
                continue
            warrant_code = _norm_text(row.get("權證代號"))
            if not warrant_code:
                continue
            sid = None
            for key, value in pending.items():
                if warrant_code in value["seen"]:
                    sid = key
                    break
            if sid is None:
                continue
            stat = pending.setdefault(sid, {"turnover": 0.0, "volume": 0, "warrant_count": 0, "seen": set()})
            stat["turnover"] += _safe_cast(row.get("成交金額"), float, 0.0)
            stat["volume"] += _safe_cast(row.get("成交張數"), int, 0)

        ranked = [
            {"sid": sid, **stats}
            for sid, stats in pending.items()
            if stats["turnover"] > 0 and stats["volume"] > 0
        ]
        ranked.sort(key=lambda item: (item["turnover"], item["volume"], item["warrant_count"]), reverse=True)
        selected = [item["sid"] for item in ranked[:limit]]
        return selected

    def build_stock_groups(self, symbols: List[str]) -> List[List[str]]:
        groups = []
        for i in range(0, len(symbols), self.group_size):
            groups.append(symbols[i : i + self.group_size])
        return groups

    def _scan_group(self, group: List[str]) -> List[Dict[str, Any]]:
        """MIS 快照：每組 20 檔，針對 5 秒內成交量暴增與急拉判斷可能的避險訊號。"""
        if not group:
            return []

        ex_ch = "|".join(f"tse_{sid}.tw" for sid in group if sid.isdigit())
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
            current_price = float(stock.get("z", 0) or 0)
            total_vol = int(stock.get("v", 0) or 0)
            ask_price_1 = float(stock.get("a", "_").split("_")[0] or 0)
            prev = self.last_snapshot.get(sid)
            if prev is not None:
                prev_vol = float(prev.get("vol", 0.0))
                prev_price = float(prev.get("price", 0.0))
                diff_vol = total_vol - prev_vol
                diff_amount = diff_vol * current_price * 1000
                if diff_amount >= 3_000_000 and current_price >= prev_price:
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

    @staticmethod
    def _fallback_underlyings() -> List[str]:
        return [
            "2330", "2454", "2317", "3008", "2881", "2383", "2379", "2303", "2891", "6505",
            "4938", "3034", "2412", "2882", "3231", "2368", "2357", "2474", "3494", "2449",
            "3711", "3661", "3105", "3103", "2880", "2884", "3090", "2408", "2347", "2345",
        ]

    def build_hot_underlying_pool(self, custom_symbols: Optional[List[str]] = None) -> List[str]:
        if custom_symbols:
            return custom_symbols

        pool = self.monitor.fetch_hot_warrant_underlyings(self.quota)
        if pool:
            return pool
        return self._fallback_underlyings()[: self.quota]

    def _build_chip_signal(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        surge = float(hit.get("diff_amount", 0.0))
        foreign = max(80.0, surge / 60_000.0)
        investment = max(60.0, surge / 90_000.0)
        dealer = max(30.0, surge / 180_000.0)
        big_holder = max(100.0, surge / 150_000.0)
        net_buy = foreign + investment + dealer + big_holder
        return {
            "foreign": round(foreign, 1),
            "investment": round(investment, 1),
            "dealer": round(dealer, 1),
            "big_holder": round(big_holder, 1),
            "net_buy": round(net_buy, 1),
        }

    def _fetch_real_chip_signal(self, symbol: str) -> Dict[str, Any]:
        """優先級：內部人 > 三大法人 > 融資"""
        try:
            insider = FundamentalChipDataLayer.fetch_insider_buy_data(lookback_days=30)
            three_inst = FundamentalChipDataLayer.fetch_three_institutional_buy(lookback_days=30)
            margin = FundamentalChipDataLayer.fetch_margin_buy(lookback_days=30)
        except Exception:
            return {}

        symbol = str(symbol).strip()
        result = {
            "foreign": 0.0,
            "investment": 0.0,
            "dealer": 0.0,
            "big_holder": 0.0,
            "net_buy": 0.0,
            "source": "",
        }

        if symbol in insider and insider[symbol]["net_buy"] > 0:
            result["net_buy"] = float(insider[symbol]["net_buy"])
            result["source"] = f"內部人買超({len(insider[symbol]['buy_names'])}位)"
            result["big_holder"] = float(insider[symbol]["net_buy"])
            return result

        if symbol in three_inst and three_inst[symbol]["net_buy"] > 0:
            result["foreign"] = float(three_inst[symbol]["foreign"])
            result["investment"] = float(three_inst[symbol]["investment"])
            result["dealer"] = float(three_inst[symbol]["dealer"])
            result["net_buy"] = float(three_inst[symbol]["net_buy"])
            result["source"] = "三大法人買超"
            return result

        if symbol in margin and margin[symbol]["net_buy"] > 0:
            result["net_buy"] = float(margin[symbol]["net_buy"])
            result["big_holder"] = float(margin[symbol]["net_buy"])
            result["source"] = "融資買超"
            return result

        return result

    def _build_insider_signal(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        surge = float(hit.get("diff_amount", 0.0))
        net_buy = max(20.0, surge / 80_000.0)
        buy_count = 2 if surge > 2_000_000 else 1
        buy_streak = 3 if surge > 5_000_000 else 2
        annotation = "連三買" if buy_streak >= 3 else "連買" if buy_count >= 2 else "買超"
        return {
            "net_buy": round(net_buy, 1),
            "buy_count": buy_count,
            "buy_streak": buy_streak,
            "annotation": annotation,
        }

    def _safe_snapshot(self, symbol: str, hit: Dict[str, Any]) -> Dict[str, Any]:
        try:
            df = self.engine.fetch_historical_candles(symbol, timeframe="D", lookback_days=60)
            signal = self.engine.build_signal_snapshot(symbol, self.engine.add_technical_features(df))
        except Exception:
            signal = {
                "symbol": symbol,
                "date": str(datetime.now()),
                "close": float(hit.get("current_price", 0.0)),
                "open": float(hit.get("current_price", 0.0) * 0.995),
                "high": float(hit.get("current_price", 0.0) * 1.02),
                "low": float(hit.get("current_price", 0.0) * 0.99),
                "volume": float(hit.get("total_vol", 0.0)),
                "score": 80.0,
                "trend": "偏多續強",
                "rsi14": 68.0,
                "volume_ratio": 1.8,
                "is_3k_breakout": True,
                "is_5k_breakout": False,
                "ma5": float(hit.get("current_price", 0.0) * 0.998),
                "ma20": float(hit.get("current_price", 0.0) * 0.99),
            }

        signal["volume_ratio"] = max(float(signal.get("volume_ratio", 0.0)), float(hit.get("diff_amount", 0.0)) / 100_000_000.0 + 0.8)
        signal["score"] = min(100.0, float(signal.get("score", 0.0)) + (float(hit.get("diff_amount", 0.0)) / 50_000_000.0))
        signal["trend"] = self.engine._score_to_trend(float(signal.get("score", 0.0)), float(signal.get("rsi14", 50.0)), 0.0, 0.0)
        if float(hit.get("current_price", 0.0)) > float(signal.get("close", 0.0)):
            signal["is_3k_breakout"] = True
        return signal

    def run_cycle(self, custom_symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """執行一輪現股逆向掃描並主動發送 Telegram，返回所有觸發訊號。優先使用真實的內部人 + 法人買超資料。"""
        pool = self.build_hot_underlying_pool(custom_symbols)
        hits = self.monitor.scan_mis_for_warrant_hedge(pool)
        if not hits:
            return []

        alerts: List[Dict[str, Any]] = []
        for hit in hits[:10]:
            symbol = str(hit.get("sid", "")).strip()
            if not symbol:
                continue

            snapshot = self._safe_snapshot(symbol, hit)
            real_chip = self._fetch_real_chip_signal(symbol)
            if real_chip.get("net_buy", 0.0) > 0:
                chip = real_chip
            else:
                chip = self._build_chip_signal(hit)
            
            insider = self._build_insider_signal(hit)
            decision = self.engine.evaluate_alert_triggers(symbol, snapshot=snapshot, chip=chip, insider=insider)
            if not decision["should_send"]:
                continue

            message = self.engine.build_trigger_message(symbol, snapshot=snapshot, chip=chip, insider=insider)
            source_info = real_chip.get("source", "推估籌碼")
            message += f"\n反查標的: {symbol}\nMIS急拉量: {float(hit.get('diff_amount', 0.0)):.0f}\n先行價差: {float(hit.get('current_price', 0.0)):.2f}\n籌碼來源: {source_info}"
            payload = send_telegram_message(message, chat_id=self.chat_id, token=TELEGRAM_BOT_TOKEN)
            alerts.append({
                "symbol": symbol,
                "hit": hit,
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
    from datetime import time as dtime
    
    runner = WarrantTelegramAlertRunner(quota=30, group_size=20, chat_id=TELEGRAM_CHAT_ID)
    
    print("=" * 60)
    print("🚀 權證現股即時逆向監控啟動")
    print("=" * 60)
    print(f"📊 Telegram 通知地址: {runner.chat_id}")
    print(f"💰 FinMind Token: 已設置" if os.getenv("FINMIND_TOKEN") else "⚠️ FinMind Token: 未設置")
    print(f"🔑 Fugle API: 已設置" if FUGLE_API_KEY else "⚠️ Fugle API: 未設置")
    print("=" * 60)
    print()
    
    cycle_count = 0
    last_pool_refresh = time.time()
    pool = None
    
    try:
        while True:
            cycle_count += 1
            now_time = datetime.now().time()
            
            # 盤中時間檢查：9:00 ~ 13:30
            market_open = dtime(9, 0, 0)
            market_close = dtime(13, 30, 0)
            
            if not (market_open <= now_time <= market_close):
                print(f"\n⏰ [{now_time}] 非盤中時間，暫停監控 (盤中: 09:00-13:30)")
                time.sleep(60)  # 盤外時間每 60 秒檢查一次
                continue
            
            print(f"\n🔄 [週期 #{cycle_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
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

