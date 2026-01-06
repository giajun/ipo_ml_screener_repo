from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf


def get_price_history(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, interval=interval, auto_adjust=False)
        if hist is None or hist.empty:
            return pd.DataFrame()
        hist.index = pd.to_datetime(hist.index)
        return hist
    except Exception:
        return pd.DataFrame()


def get_quote_info(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).fast_info
        # fast_info is limited; fallback to .info only when needed (slower).
        out = {
            "last_price": getattr(info, "last_price", None) if hasattr(info, "last_price") else info.get("last_price"),
            "market_cap": getattr(info, "market_cap", None) if hasattr(info, "market_cap") else info.get("market_cap"),
            "shares": getattr(info, "shares", None) if hasattr(info, "shares") else info.get("shares"),
        }
        # try extended fields
        try:
            info2 = yf.Ticker(ticker).info
            out.setdefault("shares_outstanding", info2.get("sharesOutstanding"))
            out.setdefault("short_name", info2.get("shortName"))
            out.setdefault("long_name", info2.get("longName"))
            out.setdefault("quote_type", info2.get("quoteType"))
        except Exception:
            pass
        return out
    except Exception:
        return {}


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def compute_momentum_features(hist: pd.DataFrame, cfg: dict) -> dict:
    # returns dict with momentum_pass + components
    if hist is None or hist.empty:
        return {"momentum_pass": False}

    close = hist["Close"].dropna()
    if len(close) < cfg["min_history_days"]:
        return {"momentum_pass": False, "reason": "insufficient_history"}

    sma_fast = sma(close, cfg["sma_fast"])
    sma_slow = sma(close, cfg["sma_slow"])
    px = float(close.iloc[-1])

    # Uptrend: price above SMA fast, SMA fast above SMA slow
    cond_trend = (px > float(sma_fast.iloc[-1])) and (float(sma_fast.iloc[-1]) > float(sma_slow.iloc[-1]))

    # Positive slope of SMA fast over last N days
    n = cfg["sma_trend_days"]
    if len(sma_fast.dropna()) < n + 1:
        cond_slope = False
    else:
        cond_slope = float(sma_fast.iloc[-1]) > float(sma_fast.iloc[-1 - n])

    # 20D return
    if len(close) < 21:
        r20 = np.nan
        cond_r20 = False
    else:
        r20 = float(close.iloc[-1] / close.iloc[-21] - 1.0)
        cond_r20 = r20 >= cfg["min_20d_return"]

    # Drawdown from 60d high
    lookback = 60
    hi = float(close.tail(lookback).max())
    dd = 0.0 if hi == 0 else float(hi - px) / hi
    cond_dd = dd <= cfg["max_drawdown_from_60d_high"]

    # Not too extended above SMA fast
    dist = 0.0 if float(sma_fast.iloc[-1]) == 0 else (px - float(sma_fast.iloc[-1])) / float(sma_fast.iloc[-1])
    cond_dist = dist <= cfg["max_distance_above_sma_fast"]

    momentum_pass = bool(cond_trend and cond_slope and cond_r20 and cond_dd and cond_dist)

    # Score 0..10
    score = 0
    score += 2 if cond_trend else 0
    score += 2 if cond_slope else 0
    score += 2 if cond_r20 else 0
    score += 2 if cond_dd else 0
    score += 2 if cond_dist else 0

    return {
        "momentum_pass": momentum_pass,
        "momentum_score_0_10": score,
        "r20": r20,
        "drawdown_from_60d_high": dd,
        "dist_above_sma_fast": dist,
        "sma_fast": float(sma_fast.iloc[-1]),
        "sma_slow": float(sma_slow.iloc[-1]),
    }
