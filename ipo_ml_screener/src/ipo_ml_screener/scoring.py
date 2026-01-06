from __future__ import annotations
import math
import pandas as pd


def _is_missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def score_hard_gates(row: dict, cfg: dict) -> dict:
    th = cfg["hard_gates"]["thresholds"]
    w = cfg["hard_gates"]["weights"]

    # Required numeric thresholds
    price_ok = (row.get("price") is not None) and (row["price"] >= th["min_price"])
    mcap_ok = (row.get("market_cap") is not None) and (row["market_cap"] >= th["min_market_cap_usd"])
    liq_ok = (row.get("avg_dollar_vol_20d") is not None) and (row["avg_dollar_vol_20d"] >= th["min_avg_dollar_volume_20d"])
    sh_ok = (row.get("shares_outstanding") is not None) and (row["shares_outstanding"] >= th["min_shares_outstanding"])

    # Optional (if missing -> neutral, but we keep a 'data_sufficient' flag)
    gm = row.get("gross_margin")
    gm_ok = True if _is_missing(gm) else (gm >= th["min_gross_margin"])

    g = row.get("yoy_revenue_growth")
    g_ok = True if _is_missing(g) else (g >= th["min_yoy_revenue_growth"])

    sbc = row.get("sbc_to_revenue")
    sbc_ok = True if _is_missing(sbc) else (sbc <= th["max_sbc_to_revenue"])

    runway = row.get("cash_runway_months")
    runway_ok = True if _is_missing(runway) else (runway >= th["min_cash_runway_months"])

    momentum_ok = bool(row.get("momentum_pass", False))

    # Weighted score (0..100)
    components = {
        "price": price_ok,
        "market_cap": mcap_ok,
        "liquidity": liq_ok,
        "shares_outstanding": sh_ok,
        "momentum": momentum_ok,
        "gross_margin": gm_ok,
        "revenue_growth": g_ok,
        "sbc": sbc_ok,
        "cash_runway": runway_ok,
    }
    total_w = sum(w.values())
    raw = sum((w[k] if components.get(k) else 0) for k in w.keys())
    total_score = 100.0 * raw / total_w if total_w else 0.0

    # Hard pass: must satisfy the core + momentum
    hard_pass = bool(price_ok and mcap_ok and liq_ok and sh_ok and momentum_ok)

    data_sufficient = not (_is_missing(gm) and _is_missing(g) and _is_missing(sbc) and _is_missing(runway))

    return {
        **{f"{k}_pass": v for k, v in components.items()},
        "total_score": total_score,
        "hard_pass": hard_pass,
        "data_sufficient_fundamentals": data_sufficient,
    }
