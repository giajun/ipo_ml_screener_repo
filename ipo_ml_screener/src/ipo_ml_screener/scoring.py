from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

import math


def _to_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return float(x)
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _get(obj: Any, key: str) -> Any:
    """
    Supports:
      - dataclass (PriceSummary)
      - dict
      - object with attribute
    """
    if obj is None:
        return None
    if is_dataclass(obj):
        d = asdict(obj)
        return d.get(key)
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def compute_hard_gates(
    price_summary: Any,
    sec_metrics: dict[str, Any] | None,
    days_since_ipo: int | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Hard-gate pass/fail used by dashboard filters.

    Design for IPO reality:
      - Market/liquidity gates are strict (because always available)
      - Fundamentals gates are "soft" when missing: missing -> marked insufficient, NOT auto-fail
        (otherwise new IPOs all fail due to missing 10-Q/10-K).

    Returns dict including:
      - pass_hard_gates
      - data_sufficient_fundamentals
      - individual gate flags and raw values
    """
    sec_metrics = sec_metrics or {}
    thresholds = thresholds or {}

    # Default thresholds (tune later in config integration)
    min_dollar_vol = float(thresholds.get("min_avg_dollar_vol_20d", 3_000_000))  # $3M/day
    min_market_cap = float(thresholds.get("min_market_cap", 200_000_000))        # $200M
    min_price = float(thresholds.get("min_price", 3.0))                          # $3

    # Liquidity / market
    avg_dollar_vol_20d = _to_float(_get(price_summary, "avg_dollar_vol_20d"))
    market_cap = _to_float(_get(price_summary, "market_cap"))
    last_close = _to_float(_get(price_summary, "last_close"))

    gate_liquidity = (avg_dollar_vol_20d is not None) and (avg_dollar_vol_20d >= min_dollar_vol)
    gate_market_cap = (market_cap is not None) and (market_cap >= min_market_cap)
    gate_price = (last_close is not None) and (last_close >= min_price)

    # Fundamentals (best-effort)
    cash = _to_float(sec_metrics.get("cash_and_equivalents"))
    cfo = _to_float(sec_metrics.get("operating_cash_flow"))
    fcf = _to_float(sec_metrics.get("free_cash_flow"))
    gross_margin = _to_float(sec_metrics.get("gross_margin"))
    sbc = _to_float(sec_metrics.get("stock_based_compensation"))

    # Determine if fundamentals are sufficient
    # (new IPOs often have only 1-2 of these)
    fundamentals_present = [v is not None for v in [cash, cfo, fcf, gross_margin, sbc]]
    data_sufficient_fundamentals = sum(fundamentals_present) >= 2

    # Optional fundamental gates (only enforced if sufficient data)
    # You can tighten later; for now keep conservative.
    gate_gross_margin = True
    if data_sufficient_fundamentals and gross_margin is not None:
        gate_gross_margin = gross_margin >= float(thresholds.get("min_gross_margin", 0.20))

    # cash runway heuristic (if we have cash and (negative) CFO or FCF)
    runway_months = None
    gate_runway = True
    burn = None
    # Prefer FCF for burn, fall back to CFO
    if fcf is not None and fcf < 0:
        burn = -fcf
    elif cfo is not None and cfo < 0:
        burn = -cfo

    if cash is not None and burn is not None and burn > 0:
        runway_months = 12.0 * (cash / burn)
        if data_sufficient_fundamentals:
            gate_runway = runway_months >= float(thresholds.get("min_runway_months", 12.0))

    # Final decision:
    # strict: liquidity + market cap + price must pass
    # fundamentals: only enforced when sufficient
    pass_hard_gates = bool(gate_liquidity and gate_market_cap and gate_price and gate_gross_margin and gate_runway)

    return {
        "pass_hard_gates": pass_hard_gates,
        "data_sufficient_fundamentals": data_sufficient_fundamentals,
        # raw
        "avg_dollar_vol_20d": avg_dollar_vol_20d,
        "market_cap": market_cap,
        "last_close": last_close,
        "cash_and_equivalents": cash,
        "operating_cash_flow": cfo,
        "free_cash_flow": fcf,
        "gross_margin": gross_margin,
        "stock_based_compensation": sbc,
        "runway_months": runway_months,
        # gates
        "gate_liquidity": gate_liquidity,
        "gate_market_cap": gate_market_cap,
        "gate_price": gate_price,
        "gate_gross_margin": gate_gross_margin,
        "gate_runway": gate_runway,
        # meta
        "days_since_ipo": days_since_ipo,
    }


def compute_total_score(
    hard_gates: dict[str, Any],
    momentum: dict[str, Any],
    price_summary: Any,
    sec_metrics: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Simple 0-100 score:
      - Liquidity/market (0-40)
      - Momentum (0-35)
      - Fundamentals (0-25) but only if sufficient data, otherwise partial.

    Returns:
      {"score_total": float, "score_components": {...}}
    """
    sec_metrics = sec_metrics or {}
    weights = weights or {}

    # Component weights
    w_liq = float(weights.get("liquidity", 40.0))
    w_mom = float(weights.get("momentum", 35.0))
    w_fund = float(weights.get("fundamentals", 25.0))

    # Liquidity score
    liq_points = 0.0
    # give points per gate
    liq_points += 0.5 if hard_gates.get("gate_liquidity") else 0.0
    liq_points += 0.3 if hard_gates.get("gate_market_cap") else 0.0
    liq_points += 0.2 if hard_gates.get("gate_price") else 0.0
    score_liq = w_liq * liq_points  # already 0..w_liq

    # Momentum score: count satisfied conditions if provided
    mom_conditions = ["cond_ma_stack", "cond_slope_up", "cond_ret", "cond_drawdown", "cond_dev"]
    mom_hits = 0
    mom_total = 0
    for k in mom_conditions:
        if k in momentum:
            mom_total += 1
            mom_hits += 1 if bool(momentum.get(k)) else 0
    if mom_total == 0:
        score_mom = 0.0
    else:
        score_mom = w_mom * (mom_hits / mom_total)

    # Fundamentals score (soft when missing)
    data_ok = bool(hard_gates.get("data_sufficient_fundamentals", False))
    fund_score_raw = 0.0
    fund_parts = 0

    gm = _to_float(sec_metrics.get("gross_margin"))
    if gm is not None:
        # normalize 0..1 with cap
        fund_score_raw += max(0.0, min(1.0, gm / 0.60))  # 60% considered excellent
        fund_parts += 1

    runway = _to_float(hard_gates.get("runway_months"))
    if runway is not None:
        fund_score_raw += max(0.0, min(1.0, runway / 24.0))  # 24 months excellent
        fund_parts += 1

    # If nothing available, fundamentals contribute small neutral value (not a penalty)
    if fund_parts == 0:
        score_fund = w_fund * (0.25 if not data_ok else 0.0)
    else:
        score_fund = w_fund * (fund_score_raw / fund_parts)

    score_total = float(max(0.0, min(100.0, score_liq + score_mom + score_fund)))

    return {
        "score_total": score_total,
        "score_components": {
            "liquidity": score_liq,
            "momentum": score_mom,
            "fundamentals": score_fund,
        },
    }
