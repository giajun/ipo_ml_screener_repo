# src/ipo_ml_screener/market.py

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd
import yfinance as yf


def _silent_call(func, *args, **kwargs):
    """
    yfinance/yahoo sometimes prints noisy messages (404, delisted warnings) to stdout/stderr.
    We silence those to keep CLI output clean.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return func(*args, **kwargs)


@dataclass
class PriceSummary:
    ticker: str
    last_close: Optional[float]
    avg_dollar_vol_20d: Optional[float]
    market_cap: Optional[float]
    currency: Optional[str]


def get_price_history(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch OHLCV history from Yahoo via yfinance.
    Returns empty DataFrame if no data is available.
    """
    t = yf.Ticker(ticker)

    # yfinance may print errors; silence them
    try:
        hist = _silent_call(t.history, period=period, interval=interval, auto_adjust=False)
    except Exception:
        return pd.DataFrame()

    if hist is None or hist.empty:
        return pd.DataFrame()

    # Normalize columns and index
    if not isinstance(hist.index, pd.DatetimeIndex):
        try:
            hist.index = pd.to_datetime(hist.index)
        except Exception:
            pass

    # Ensure expected columns exist
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in hist.columns:
            hist[col] = pd.NA

    return hist


def get_quote_fast_info(ticker: str) -> dict[str, Any]:
    """
    Fetch fast_info if available (lighter than .info).
    Returns {} if not available.
    """
    try:
        return _silent_call(lambda: yf.Ticker(ticker).fast_info) or {}
    except Exception:
        return {}


def get_quote_info(ticker: str) -> dict[str, Any]:
    """
    Fetch full quote info (.info). This can be slow and sometimes noisy; we silence it.
    Returns {} on failure.
    """
    try:
        return _silent_call(lambda: yf.Ticker(ticker).info) or {}
    except Exception:
        return {}


def compute_price_summary(ticker: str, hist: pd.DataFrame) -> PriceSummary:
    """
    Compute a few market/price features used by hard gates:
    - last_close
    - avg_dollar_vol_20d = mean(Close * Volume) over last 20 trading days
    - market_cap (from fast_info/info if available)
    """
    last_close: Optional[float] = None
    avg_dollar_vol_20d: Optional[float] = None

    if hist is not None and not hist.empty:
        try:
            last_close = float(hist["Close"].dropna().iloc[-1])
        except Exception:
            last_close = None

        try:
            tail = hist[["Close", "Volume"]].dropna().tail(20)
            if not tail.empty:
                avg_dollar_vol_20d = float((tail["Close"] * tail["Volume"]).mean())
        except Exception:
            avg_dollar_vol_20d = None

    # Market cap: prefer fast_info, fall back to info
    market_cap: Optional[float] = None
    currency: Optional[str] = None

    fi = get_quote_fast_info(ticker)
    if fi:
        # keys vary; try best-effort
        market_cap = fi.get("market_cap") or fi.get("marketCap") or market_cap
        currency = fi.get("currency") or currency

    if market_cap is None:
        info = get_quote_info(ticker)
        market_cap = info.get("marketCap") if info else None
        currency = currency or (info.get("currency") if info else None)

    # ensure numeric
    try:
        market_cap = float(market_cap) if market_cap is not None else None
    except Exception:
        market_cap = None

    return PriceSummary(
        ticker=ticker,
        last_close=last_close,
        avg_dollar_vol_20d=avg_dollar_vol_20d,
        market_cap=market_cap,
        currency=currency,
    )


def is_equity_like(ticker: str) -> bool:
    """
    Best-effort check: filter out non-equity instruments (warrants/units/etc).
    Yahoo's 'quoteType' is not always reliable, but helps reduce junk.
    """
    fi = get_quote_fast_info(ticker)
    qt = None

    # fast_info might not have quoteType; use .info fallback if needed
    if fi:
        try:
            qt = fi.get("quoteType")
        except (KeyError, AttributeError):
            qt = None

    if qt is None:
        info = get_quote_info(ticker)
        qt = info.get("quoteType") if info else None

    if qt is None:
        # unknown -> don't block
        return True

    return str(qt).upper() in {"EQUITY", "ETF"}  # keep ETF if any sneaks in


def compute_momentum_features(hist: pd.DataFrame, momentum_cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Compute momentum features based on price history:
    - sma_fast and sma_slow (simple moving averages)
    - return_20d (20-day return)
    - drawdown_from_60d_high (distance from 60-day high)
    - distance_above_sma_fast (how far price is above SMA fast)

    Returns a dict with these features or None values if insufficient data.
    """
    features = {
        "sma_fast": None,
        "sma_slow": None,
        "return_20d": None,
        "drawdown_from_60d_high": None,
        "distance_above_sma_fast": None,
    }

    if hist is None or hist.empty or "Close" not in hist.columns:
        return features

    close = hist["Close"].dropna()
    if len(close) < momentum_cfg.get("min_history_days", 60):
        return features

    # SMA fast and slow
    sma_fast_period = momentum_cfg.get("sma_fast", 20)
    sma_slow_period = momentum_cfg.get("sma_slow", 50)

    try:
        sma_fast = close.rolling(window=sma_fast_period).mean().iloc[-1]
        features["sma_fast"] = float(sma_fast) if pd.notna(sma_fast) else None
    except Exception:
        pass

    try:
        sma_slow = close.rolling(window=sma_slow_period).mean().iloc[-1]
        features["sma_slow"] = float(sma_slow) if pd.notna(sma_slow) else None
    except Exception:
        pass

    # 20-day return
    try:
        if len(close) >= 20:
            return_20d = (close.iloc[-1] / close.iloc[-20]) - 1
            features["return_20d"] = float(return_20d) if pd.notna(return_20d) else None
    except Exception:
        pass

    # Drawdown from 60-day high
    try:
        if len(close) >= 60:
            high_60d = close.tail(60).max()
            current = close.iloc[-1]
            drawdown = (current / high_60d) - 1  # negative value means drawdown
            features["drawdown_from_60d_high"] = float(drawdown) if pd.notna(drawdown) else None
    except Exception:
        pass

    # Distance above SMA fast
    try:
        if features["sma_fast"] is not None:
            current = close.iloc[-1]
            distance = (current / features["sma_fast"]) - 1
            features["distance_above_sma_fast"] = float(distance) if pd.notna(distance) else None
    except Exception:
        pass

    return features
