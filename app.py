
import os, time, math
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(
    page_title="Market Risk Dashboard",
    page_icon="⚠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

FRED_KEY = st.secrets.get("FRED_API_KEY", os.getenv("FRED_API_KEY", ""))
if FRED_KEY in ["your_fred_api_key", "your_fred_key"]:
    FRED_KEY = ""
MASSIVE_KEY = st.secrets.get("MASSIVE_API_KEY", os.getenv("MASSIVE_API_KEY", ""))
if MASSIVE_KEY in ["your_massive_api_key", "your_massive_key"]:
    MASSIVE_KEY = ""
REFRESH_SECONDS = int(st.secrets.get("REFRESH_SECONDS", os.getenv("REFRESH_SECONDS", "300")))

# -----------------------------
# Data definitions
# -----------------------------
FRED = {
    "VIX": ("VIXCLS", "VIX", "volatility", "lower"),
    "HY Spread": ("BAMLH0A0HYM2", "US HY OAS", "credit", "lower"),
    "BB Spread": ("BAMLH0A1HYBB", "BB OAS", "credit", "lower"),
    "CCC Spread": ("BAMLH0A3HYC", "CCC & Lower OAS", "credit", "lower"),
    "10Y Treasury": ("DGS10", "10Y Treasury", "rates", "lower"),
    "2Y Treasury": ("DGS2", "2Y Treasury", "rates", "lower"),
    "10Y-2Y": ("T10Y2Y", "10Y-2Y Curve", "rates", "higher"),
    "10Y-3M": ("T10Y3M", "10Y-3M Curve", "rates", "higher"),
    "10Y Breakeven": ("T10YIE", "10Y Breakeven", "inflation", "lower"),
    "Unemployment": ("UNRATE", "Unemployment", "growth", "lower"),
    "Initial Claims": ("ICSA", "Initial Claims", "growth", "lower"),
    "Continuing Claims": ("CCSA", "Continuing Claims", "growth", "lower"),
    "Fed Funds": ("FEDFUNDS", "Fed Funds", "rates", "lower"),
    "Financial Conditions": ("NFCI", "Chicago Fed NFCI", "credit", "lower"),
    "Real GDP": ("A191RL1Q225SBEA", "Real GDP QoQ SAAR", "growth", "higher"),
    "CPI": ("CPIAUCSL", "CPI", "inflation", "lower"),
    "Core CPI": ("CPILFESL", "Core CPI", "inflation", "lower"),
    "PPI": ("PPIACO", "PPI", "inflation", "lower"),
    "Retail Sales": ("RSAFS", "Retail Sales", "growth", "higher"),
    "Industrial Production": ("INDPRO", "Industrial Production", "growth", "higher"),
    "Consumer Sentiment": ("UMCSENT", "UMich Sentiment", "growth", "higher"),
    "M2": ("M2SL", "M2", "liquidity", "higher"),
    "SOFR": ("SOFR", "SOFR", "rates", "lower"),
}

MARKET_TICKERS = {
    "S&P 500": "I:SPX",
    "Nasdaq 100": "I:NDX",
    "Dow Jones": "I:DJI",
    "Russell 2000": "I:RUT",
}

# Thresholds are intentionally conservative. They are a risk dashboard,
# not a calibrated probability model.
THRESHOLDS = {
    "VIX": [(15,"Normal"), (20,"Watch"), (30,"Warning"), (40,"Crisis")],
    "HY Spread": [(3.5,"Normal"), (5.0,"Watch"), (7.0,"Warning"), (10.0,"Crisis")],
    "BB Spread": [(3.0,"Normal"), (4.5,"Watch"), (6.0,"Warning"), (8.0,"Crisis")],
    "CCC Spread": [(7.0,"Normal"), (10.0,"Watch"), (13.0,"Warning"), (18.0,"Crisis")],
    "10Y Treasury": [(5.0,"Normal"), (5.5,"Watch"), (6.0,"Warning"), (6.5,"Crisis")],
    "10Y-2Y": [(-0.25,"Warning"), (0.0,"Watch"), (0.5,"Normal"), (1.0,"Normal")],
    "10Y-3M": [(-0.25,"Warning"), (0.0,"Watch"), (0.5,"Normal"), (1.0,"Normal")],
    "10Y Breakeven": [(2.5,"Normal"), (3.0,"Watch"), (3.5,"Warning"), (4.0,"Crisis")],
    "Unemployment": [(4.5,"Normal"), (5.0,"Watch"), (5.5,"Warning"), (6.0,"Crisis")],
    "Financial Conditions": [(0.0,"Normal"), (0.5,"Watch"), (1.0,"Warning"), (2.0,"Crisis")],
}

def level_for(name, value):
    if value is None or pd.isna(value):
        return "N/A"
    t = THRESHOLDS.get(name)
    if not t:
        return "Info"
    # Curves are bad when negative; otherwise values rise into danger.
    if name in ("10Y-2Y","10Y-3M"):
        if value < -0.25: return "Crisis"
        if value < 0: return "Warning"
        if value < 0.5: return "Watch"
        return "Normal"
    if name in ("10Y Treasury",):
        if value >= 6.0: return "Crisis"
        if value >= 5.5: return "Warning"
        if value >= 5.0: return "Watch"
        return "Normal"
    for threshold, label in reversed(t):
        if value >= threshold:
            return label
    return "Normal"

def score_level(level):
    return {"Normal":0, "Watch":1, "Warning":2, "Crisis":3}.get(level, 0)

@st.cache_data(ttl=300)
def fred_series(series_id, days=750):
    if not FRED_KEY:
        return pd.DataFrame()
    end = datetime.now().date()
    start = end - timedelta(days=days)
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "observation_start": str(start),
        "observation_end": str(end),
        "sort_order": "asc",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
    except requests.exceptions.RequestException:
        return pd.DataFrame()
    rows = []
    for x in r.json().get("observations", []):
        try:
            v = float(x["value"])
            if math.isfinite(v):
                rows.append((pd.to_datetime(x["date"]), v))
        except Exception:
            pass
    return pd.DataFrame(rows, columns=["date","value"]).set_index("date")

def massive_snapshot(tickers):
    if not MASSIVE_KEY:
        return {}
    url = "https://api.massive.com/v3/snapshot/indices"
    params = {"apiKey": MASSIVE_KEY, "limit": 250}
    # API supports ticker filtering; requesting one by one makes error handling simpler.
    out = {}
    for ticker in tickers:
        p = dict(params)
        p["ticker"] = ticker
        try:
            r = requests.get(url, params=p, timeout=10)
            r.raise_for_status()
        except requests.exceptions.RequestException:
            continue
        for x in r.json().get("results", []):
            if x.get("value") is not None:
                out[x["ticker"]] = x
    return out

def get_market_data():
    try:
        return massive_snapshot(list(MARKET_TICKERS.values()))
    except Exception:
        return {}

def latest(name):
    sid = FRED[name][0]
    df = fred_series(sid, 90)
    return None if df.empty else float(df["value"].iloc[-1])

def change_1w(name):
    sid = FRED[name][0]
    df = fred_series(sid, 30)
    if len(df) < 2:
        return None
    target = df.iloc[-1]["value"]
    old = df.iloc[max(0, len(df)-6)]["value"]
    return target - old

def pct_change_1w(name):
    sid = FRED[name][0]
    df = fred_series(sid, 30)
    if len(df) < 2:
        return None
    a = df.iloc[-1]["value"]; b = df.iloc[max(0, len(df)-6)]["value"]
    return (a/b - 1)*100 if b else None

def market_card(name, x):
    if not x:
        return None
    s = x.get("session", {})
    return {
        "name": name,
        "value": x.get("value"),
        "change": s.get("change"),
        "change_pct": s.get("change_percent"),
        "status": x.get("market_status"),
        "timeframe": x.get("timeframe"),
    }

def risk_score():
    names = ["VIX","HY Spread","BB Spread","CCC Spread","10Y Treasury",
             "10Y-2Y","10Y-3M","10Y Breakeven","Unemployment","Financial Conditions"]
    vals = {}
    for n in names:
        v = latest(n)
        vals[n] = (v, level_for(n,v))
    raw = sum(score_level(l) for _,l in vals.values())
    # 30 max -> 100
    return min(100, round(raw / (len(names)*3) * 100)), vals

def recession_composite(vals):
    # A transparent, deliberately simple composite. It is NOT a statistical
    # recession probability. It highlights simultaneous deterioration.
    points = 0
    if vals["HY Spread"][0] is not None and vals["HY Spread"][0] >= 5: points += 2
    if vals["VIX"][0] is not None and vals["VIX"][0] >= 30: points += 2
    if vals["Unemployment"][0] is not None and vals["Unemployment"][0] >= 5: points += 2
    if vals["10Y-3M"][0] is not None and vals["10Y-3M"][0] < 0: points += 2
    if vals["Financial Conditions"][0] is not None and vals["Financial Conditions"][0] >= 0.5: points += 2
    return min(10, points)

def color_for(level):
    return {"Normal":"#1f9d55","Watch":"#d99b00","Warning":"#e67e22","Crisis":"#c0392b"}.get(level, "#777")

# -----------------------------
# Header
# -----------------------------
st.title("⚠️ Market Risk Dashboard")
st.caption("A transparent, rules-based early-warning system for tail risk. Risk = S&P 500 drawdown >50%.")

if not FRED_KEY:
    st.warning("FRED_API_KEY is not configured. Add it to your hosting provider's secrets/environment variables.")
if not MASSIVE_KEY:
    st.info("MASSIVE_API_KEY is not configured. Macro indicators will still work; real-time index quotes require a market-data provider key.")

with st.sidebar:
    st.header("Controls")
    refresh = st.slider("Refresh interval (minutes)", 1, 60, max(1, REFRESH_SECONDS//60))
    st.caption("Macro data updates when released. Market quotes can update intraday.")
    st.divider()
    st.subheader("Risk definition")
    st.metric("S&P 500 risk level", "50% below peak/reference")
    st.caption("The dashboard does not predict a risk event from one indicator. It looks for simultaneous stress across volatility, credit, rates, inflation, growth and liquidity.")
    st.divider()
    st.subheader("Data sources")
    st.write("• FRED / Federal Reserve Bank of St. Louis")
    st.write("• Massive market-data API")
    st.write("• S&P 500 / Cboe / Treasury / BLS / BEA series via FRED")

# -----------------------------
# Live market strip
# -----------------------------
mkt = get_market_data()
cols = st.columns(4)
for col, (label, ticker) in zip(cols, MARKET_TICKERS.items()):
    d = market_card(label, mkt.get(ticker))
    with col:
        if d:
            delta = f"{d['change_pct']:+.2f}%" if d["change_pct"] is not None else None
            st.metric(label, f"{d['value']:,.2f}", delta)
            st.caption(f"{d['timeframe']} · {d['status']}")
        else:
            st.metric(label, "—")
            st.caption("Market quote unavailable")

st.divider()

score, vals = risk_score()
rec = recession_composite(vals)
score_label = "NORMAL" if score < 25 else "WATCH" if score < 50 else "WARNING" if score < 75 else "CRISIS"
score_color = color_for(score_label.title())

c1,c2,c3,c4 = st.columns(4)
with c1:
    st.metric("Risk Score", f"{score}/100", score_label)
with c2:
    st.metric("Recession Stress Composite", f"{rec}/10", "rules-based")
with c3:
    v = latest("VIX")
    st.metric("VIX", "—" if v is None else f"{v:.2f}", level_for("VIX",v))
with c4:
    hy = latest("HY Spread")
    st.metric("HY OAS", "—" if hy is None else f"{hy:.2f}%", level_for("HY Spread",hy))

st.markdown(f"### Overall regime: <span style='color:{score_color}'>{score_label}</span>", unsafe_allow_html=True)

# -----------------------------
# Indicator grid
# -----------------------------
TRIGGERS = {
    "VIX": ">= 30",
    "HY Spread": ">= 5%",
    "CCC Spread": ">= 13%",
    "10Y-3M": "< 0%",
    "Unemployment": ">= 5.5%",
    "10Y Breakeven": ">= 3.5%",
    "Financial Conditions": ">= 1.0",
}

st.subheader("Early-warning indicators")
groups = [
    ("Volatility & Market Stress", ["VIX"]),
    ("Credit Stress", ["HY Spread","BB Spread","CCC Spread","Financial Conditions"]),
    ("Rates & Liquidity", ["10Y Treasury","2Y Treasury","10Y-2Y","10Y-3M","SOFR","Fed Funds","M2"]),
    ("Inflation", ["CPI","Core CPI","PPI","10Y Breakeven"]),
    ("Growth & Labor", ["Unemployment","Initial Claims","Continuing Claims","Real GDP","Retail Sales","Industrial Production","Consumer Sentiment"]),
]
for title, names in groups:
    st.markdown(f"#### {title}")
    columns = st.columns(4)
    for i, n in enumerate(names):
        with columns[i % 4]:
            v = latest(n)
            lev = level_for(n,v)
            delta = change_1w(n)
            unit = "%" if n not in ("VIX","Initial Claims","Continuing Claims","Consumer Sentiment","Retail Sales","Industrial Production","M2") else ""
            if n in ("HY Spread","BB Spread","CCC Spread","10Y Treasury","2Y Treasury","10Y-2Y","10Y-3M","10Y Breakeven","Fed Funds","SOFR","Financial Conditions"):
                txt = "—" if v is None else f"{v:.2f}%"
            elif n == "VIX":
                txt = "—" if v is None else f"{v:.2f}"
            else:
                txt = "—" if v is None else f"{v:,.2f}"
            st.metric(n, txt, None if delta is None else f"{delta:+.2f} 1w")
            trigger_text = f" | Trigger: {TRIGGERS[n]}" if n in TRIGGERS else ""
            st.caption(f"{lev}{trigger_text}")

# -----------------------------
# Historical charts
# -----------------------------
st.divider()
st.subheader("Trend monitor")
selected = st.multiselect(
    "Choose indicators",
    list(FRED.keys()),
    default=["VIX","HY Spread","10Y-2Y","Unemployment","10Y Breakeven"]
)
window = st.selectbox("History", ["6 months","1 year","3 years","10 years"], index=1)
days = {"6 months":180,"1 year":365,"3 years":1095,"10 years":3650}[window]

for n in selected:
    df = fred_series(FRED[n][0], days)
    if df.empty:
        continue
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df.value, mode="lines", name=n))
    fig.update_layout(height=260, margin=dict(l=10,r=10,t=35,b=10), title=n, template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Risk trigger matrix
# -----------------------------
st.divider()
st.subheader("Risk trigger matrix")
trigger_rows = [
    ("VIX", ">= 30", "Volatility regime shift"),
    ("HY Spread", ">= 5%", "Credit stress"),
    ("CCC Spread", ">= 13%", "Distressed credit"),
    ("10Y-3M", "< 0%", "Yield-curve recession signal"),
    ("Unemployment", ">= 5.5%", "Labor deterioration"),
    ("10Y Breakeven", ">= 3.5%", "Inflation expectations"),
    ("Financial Conditions", ">= 1.0", "Tight financial conditions"),
    ("S&P 500", "below 200-day MA by >10%", "Trend break"),
    ("AI/semiconductor breadth", "multiple leaders below 200DMA", "AI capex cycle warning"),
    ("Oil", "> $110", "Stagflation/geopolitical shock"),
]
df = pd.DataFrame(trigger_rows, columns=["Indicator","Trigger","Why it matters"])
st.dataframe(df, use_container_width=True, hide_index=True)

st.info(
    "Interpretation: one red indicator is noise; several independent red indicators "
    "appearing together are the signal. The dashboard is intentionally transparent so "
    "you can audit or modify every threshold."
)

st.caption(
    f"Last refresh: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')} · "
    f"Auto-refresh target: {refresh} min"
)

# Streamlit's built-in rerun
time.sleep(0.1)
