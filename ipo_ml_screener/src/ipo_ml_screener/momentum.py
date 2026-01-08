from __future__ import annotations

import numpy as np
import pandas as pd


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _slope_last_n(y: pd.Series, n: int) -> float | None:
    """
    Simple linear regression slope on last n points.
    Returns None if not enough data.
    """
    y = y.dropna().tail(n)
    if len(y) < n:
        return None
    x = np.arange(n, dtype=float)
    yy = y.to_numpy(dtype=float)
    vx = np.var(x)
    if vx == 0:
        return None
    return float(np.cov(x, yy, bias=True)[0, 1] / vx)


def compute_momentum_flags(
    hist: pd.DataFrame,
    sma_fast: int = 20,
    sma_slow: int = 50,
    slope_window: int = 20,
    ret_window: int = 20,
    ret_min: float = 0.05,          # +5%
    peak_window: int = 60,
    max_drawdown: float = 0.08,     # <= 8% below 60D high
    max_dev_sma_fast: float = 0.15, # <= 15% above SMA20
) -> dict[str, object]:
    """
    'Left-of-peak' uptrend proxy:
      - Close > SMA20 > SMA50
      - SMA20 slope positive over last slope_window
      - 20D return >= ret_min
      - drawdown from 60D high <= max_drawdown
      - price deviation from SMA20 <= max_dev_sma_fast (avoid overly extended)

    Returns a dict of flags + pass_momentum.
    """
    if hist is None or hist.empty or "Close" not in hist.columns:
        return {"pass_momentum": False, "reason": "no_price_data"}

    close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    if close.empty or len(close) < max(sma_slow, peak_window, ret_window) + 5:
        return {"pass_momentum": False, "reason": "insufficient_history", "n_close": int(len(close))}

    sma20 = _sma(close, sma_fast)
    sma50 = _sma(close, sma_slow)

    last_close = float(close.iloc[-1])
    last_sma20 = float(sma20.iloc[-1]) if not pd.isna(sma20.iloc[-1]) else None
    last_sma50 = float(sma50.iloc[-1]) if not pd.isna(sma50.iloc[-1]) else None

    cond_ma_stack = (
        (last_sma20 is not None)
        and (last_sma50 is not None)
        and (last_close > last_sma20 > last_sma50)
    )

    slope = _slope_last_n(sma20, slope_window)
    cond_slope_up = (slope is not None) and (slope > 0)

    c0 = close.shift(ret_window).iloc[-1]
    cond_ret = False
    ret = None
    if pd.notna(c0) and float(c0) > 0:
        ret = (last_close / float(c0)) - 1.0
        cond_ret = ret >= ret_min

    peak = close.tail(peak_window).max()
    dd = None
    cond_drawdown = False
    if pd.notna(peak) and float(peak) > 0:
        dd = 1.0 - (last_close / float(peak))
        cond_drawdown = dd <= max_drawdown

    dev = None
    cond_dev = False
    if last_sma20 is not None and last_sma20 > 0:
        dev = (last_close / last_sma20) - 1.0
        cond_dev = dev <= max_dev_sma_fast

    pass_momentum = bool(cond_ma_stack and cond_slope_up and cond_ret and cond_drawdown and cond_dev)

    return {
        "pass_momentum": pass_momentum,
        "cond_ma_stack": bool(cond_ma_stack),
        "cond_slope_up": bool(cond_slope_up),
        "cond_ret": bool(cond_ret),
        "cond_drawdown": bool(cond_drawdown),
        "cond_dev": bool(cond_dev),
        "last_close": last_close,
        "last_sma_fast": last_sma20,
        "last_sma_slow": last_sma50,
        "sma_fast_slope": slope,
        "ret_window": ret_window,
        "ret": ret,
        "peak_window": peak_window,
        "drawdown_from_peak": dd,
        "dev_from_sma_fast": dev,
    }
