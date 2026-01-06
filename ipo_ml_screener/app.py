import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from ipo_ml_screener.config import load_config
from ipo_ml_screener.io_utils import load_scores
from ipo_ml_screener.market import get_price_history


st.set_page_config(page_title="IPO ML Screener", layout="wide")

cfg = load_config()

st.title("IPO ML Screener — AI × Industry 4.0 / Robotics")
st.caption("Recent IPOs + hard-gate scoring + 'left-of-peak' uptrend filter")

scores_path = cfg["output"]["processed_path"]
df = load_scores(scores_path)

if df.empty:
    st.warning("No data found. Run: `python -m ipo_ml_screener.cli.refresh` first.")
    st.stop()

# Sidebar filters
st.sidebar.header("Filters")
min_score = st.sidebar.slider("Min total score", 0.0, 100.0, 70.0, 1.0)
pass_only = st.sidebar.checkbox("Hard gates: PASS only", value=True)
min_days_since_ipo = st.sidebar.slider("Min days since IPO", 0, 365, 30, 5)
max_days_since_ipo = st.sidebar.slider("Max days since IPO", 0, 365, 365, 5)

cols = ["ticker", "name", "ipo_date", "days_since_ipo", "total_score", "hard_pass",
        "momentum_pass", "avg_dollar_vol_20d", "market_cap", "price", "shares_outstanding"]
show_cols = [c for c in cols if c in df.columns]

df["ipo_date"] = pd.to_datetime(df["ipo_date"], errors="coerce")
df["days_since_ipo"] = pd.to_numeric(df["days_since_ipo"], errors="coerce")

f = df.copy()
f = f[(f["total_score"] >= min_score)]
f = f[(f["days_since_ipo"] >= min_days_since_ipo) & (f["days_since_ipo"] <= max_days_since_ipo)]
if pass_only and "hard_pass" in f.columns:
    f = f[f["hard_pass"] == True]

st.subheader("Results")
st.dataframe(
    f.sort_values(["total_score", "avg_dollar_vol_20d"], ascending=[False, False])[show_cols],
    use_container_width=True,
    height=520
)

st.divider()

st.subheader("Ticker details")
ticker = st.selectbox("Select a ticker", f["ticker"].dropna().unique().tolist())

row = df[df["ticker"] == ticker].iloc[0].to_dict()
c1, c2, c3, c4 = st.columns(4)

c1.metric("Total score", f"{row.get('total_score', float('nan')):.1f}")
c2.metric("Hard pass", "PASS" if row.get("hard_pass") else "FAIL")
c3.metric("Momentum pass", "PASS" if row.get("momentum_pass") else "FAIL")
c4.metric("Days since IPO", int(row.get("days_since_ipo", 0) or 0))

with st.expander("Raw metrics (selected)"):
    st.json({k: row.get(k) for k in sorted(row.keys())})

# Price chart
hist = get_price_history(ticker, period="1y")
if hist is not None and not hist.empty:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=hist.index,
        open=hist["Open"], high=hist["High"], low=hist["Low"], close=hist["Close"],
        name=ticker
    ))
    fig.update_layout(height=420, xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Price history not available for this ticker.")
