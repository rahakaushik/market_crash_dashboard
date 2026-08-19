import os
import math
import sys
from datetime import datetime, timedelta
import pandas as pd
import requests
import yfinance as yf
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv

# Try to load .env, but also attempt to parse .streamlit/secrets.toml as a fallback if needed.
load_dotenv()
try:
    import tomllib
    if os.path.exists(".streamlit/secrets.toml"):
        with open(".streamlit/secrets.toml", "rb") as f:
            secrets = tomllib.load(f)
        if "FRED_API_KEY" in secrets: os.environ.setdefault("FRED_API_KEY", secrets["FRED_API_KEY"])
except ImportError:
    pass

FRED_KEY = os.getenv("FRED_API_KEY", "")
if FRED_KEY in ["your_fred_api_key", "your_fred_key"]:
    FRED_KEY = ""


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
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "Dow Jones": "^DJI",
    "Russell 2000": "^RUT",
}

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

TRIGGERS = {
    "VIX": ">= 30",
    "HY Spread": ">= 5%",
    "CCC Spread": ">= 13%",
    "10Y-3M": "< 0%",
    "Unemployment": ">= 5.5%",
    "10Y Breakeven": ">= 3.5%",
    "Financial Conditions": ">= 1.0",
    "AI/Semiconductor Breadth": "< 200 DMA",
    "SKEW Index": ">= 140",
    "High-Beta/Low-Vol Ratio": "< 10-day MA (Falling)",
    "Copper/Gold Ratio": "< 10-day MA (Falling)",
    "Lumber/Gold Ratio": "< 10-day MA (Falling)",
}

DESCRIPTIONS = {
    "VIX": "Measures market expectation of near-term volatility based on S&P 500 index options.",
    "HY Spread": "Difference in yield between high-yield (junk) corporate bonds and US Treasuries.",
    "BB Spread": "Yield spread of BB-rated corporate bonds, the highest tier of high-yield debt.",
    "CCC Spread": "Yield spread of CCC-rated or lower corporate bonds, representing distressed credit.",
    "10Y Treasury": "Current yield on the 10-year US Treasury note.",
    "2Y Treasury": "Current yield on the 2-year US Treasury note.",
    "10Y-2Y": "Yield difference between 10-year and 2-year Treasuries. Negative implies an inverted curve.",
    "10Y-3M": "Yield difference between 10-year and 3-month Treasuries. A key recession predictor.",
    "10Y Breakeven": "Market's inflation expectation over the next 10 years, derived from TIPS.",
    "Unemployment": "Percentage of the labor force that is unemployed and actively seeking employment.",
    "Initial Claims": "Number of individuals filing for unemployment insurance for the first time.",
    "Continuing Claims": "Number of people continuing to receive unemployment benefits.",
    "Fed Funds": "The target interest rate set by the Federal Reserve for interbank lending.",
    "Financial Conditions": "Chicago Fed index measuring risk, credit, and leverage. Positive means tighter.",
    "Real GDP": "Inflation-adjusted measure that reflects the value of all goods and services produced.",
    "CPI": "Consumer Price Index, measuring average change over time in prices paid by consumers.",
    "Core CPI": "CPI excluding volatile food and energy components.",
    "PPI": "Producer Price Index, measuring average change in selling prices received by producers.",
    "Retail Sales": "Measure of the total receipts of retail and food services stores.",
    "Industrial Production": "Measure of the real output of manufacturing, mining, and electric/gas utilities.",
    "Consumer Sentiment": "University of Michigan survey assessing consumer confidence and economic outlook.",
    "M2": "Broad measure of money supply including cash, checking deposits, and near money.",
    "SOFR": "Secured Overnight Financing Rate, a measure of the cost of borrowing cash overnight.",
    "AI/Semiconductor Breadth": "Tracks the VanEck Semiconductor ETF (SMH) vs its 200-day moving average. A proxy for AI capex cycle strength.",
    "SKEW Index": "CBOE SKEW Index measures the perceived tail risk in S&P 500 options. High values mean investors are buying crash protection.",
    "High-Beta/Low-Vol Ratio": "Ratio of SPHB to SPLV. A declining ratio indicates investors are rushing to safe-haven stocks (risk-off).",
    "Copper/Gold Ratio": "Copper represents economic growth while gold is a safe haven. A falling ratio signals economic slowdown expectations.",
    "Lumber/Gold Ratio": "Classic macro risk-on/risk-off indicator. Lumber is tied to housing and growth; gold to safety."
}

def level_for(name, value):
    if value is None or pd.isna(value):
        return "N/A"
    t = THRESHOLDS.get(name)
    if not t:
        return "Info"
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

# Simple caching to avoid spamming the API during same run (mostly for plotting later)
_FRED_CACHE = {}

def fred_series(series_id, days=750):
    cache_key = f"{series_id}_{days}"
    if cache_key in _FRED_CACHE:
        return _FRED_CACHE[cache_key]
        
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
    df = pd.DataFrame(rows, columns=["date","value"]).set_index("date")
    _FRED_CACHE[cache_key] = df
    return df

def yfinance_snapshot(tickers):
    out = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if len(hist) >= 2:
                current = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2])
                change_pct = ((current - prev) / prev) * 100
                out[ticker] = {
                    "value": current,
                    "change_percent": change_pct,
                    "market_status": "Closed" if hist.index[-1].date() < datetime.now().date() else "Open",
                    "timeframe": "1D"
                }
        except Exception:
            pass
    return out

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

def market_card(name, x):
    if not x:
        return None
    return {
        "name": name,
        "value": f"{x.get('value'):,.2f}" if x.get('value') is not None else "—",
        "change_pct": f"{x.get('change_percent'):+.2f}%" if x.get('change_percent') is not None else "",
        "status": x.get("market_status", "Unknown"),
        "timeframe": x.get("timeframe", "Unknown"),
    }

def get_indicator_data(n):
    if n == "AI/Semiconductor Breadth":
        try:
            t = yf.Ticker("SMH")
            hist = t.history(period="1y")
            if len(hist) > 200:
                v = float(hist['Close'].iloc[-1])
                ma = float(hist['Close'].rolling(200).mean().iloc[-1])
                lev = "Warning" if v < ma else "Normal"
                delta = v - float(hist['Close'].iloc[-6]) if len(hist) > 6 else 0
                txt = f"${v:.2f}"
                delta_txt = f"{delta:+.2f} 1w"
                trigger_text = f"Trigger: {TRIGGERS.get(n, '')} (200DMA: ${ma:.2f})"
                return v, lev, delta, txt, delta_txt, trigger_text
        except Exception:
            pass
        return None, "N/A", None, "—", "", ""
    elif n == "SKEW Index":
        try:
            hist = yf.Ticker("^SKEW").history(period="1mo")
            if len(hist) > 0:
                v = float(hist['Close'].iloc[-1])
                lev = "Warning" if v >= 140 else "Watch" if v >= 130 else "Normal"
                delta = v - float(hist['Close'].iloc[-6]) if len(hist) > 6 else 0
                txt = f"{v:.2f}"
                delta_txt = f"{delta:+.2f} 1w"
                trigger_text = f"Trigger: {TRIGGERS.get(n, '')}"
                return v, lev, delta, txt, delta_txt, trigger_text
        except Exception:
            pass
        return None, "N/A", None, "—", "", ""
    elif n in ("High-Beta/Low-Vol Ratio", "Copper/Gold Ratio", "Lumber/Gold Ratio"):
        try:
            t1, t2 = {"High-Beta/Low-Vol Ratio": ("SPHB", "SPLV"), 
                      "Copper/Gold Ratio": ("HG=F", "GC=F"),
                      "Lumber/Gold Ratio": ("LBR=F", "GC=F")}[n]
            h1 = yf.Ticker(t1).history(period="1mo")['Close'].dropna()
            h2 = yf.Ticker(t2).history(period="1mo")['Close'].dropna()
            if len(h1) > 0 and len(h2) > 0:
                ratio_series = (h1 / h2).dropna()
                v = float(ratio_series.iloc[-1])
                ma = float(ratio_series.rolling(10).mean().iloc[-1]) if len(ratio_series) >= 10 else v
                lev = "Warning" if v < ma else "Normal"
                delta = v - float(ratio_series.iloc[-6]) if len(ratio_series) > 6 else 0
                txt = f"{v:.3f}"
                delta_txt = f"{delta:+.3f} 1w"
                trigger_text = f"Trigger: {TRIGGERS.get(n, '')}"
                return v, lev, delta, txt, delta_txt, trigger_text
        except Exception:
            pass
        return None, "N/A", None, "—", "", ""
    else:
        v = latest(n)
        lev = level_for(n,v)
        delta = change_1w(n)
        if n in ("HY Spread","BB Spread","CCC Spread","10Y Treasury","2Y Treasury","10Y-2Y","10Y-3M","10Y Breakeven","Fed Funds","SOFR","Financial Conditions"):
            txt = "—" if v is None else f"{v:.2f}%"
        elif n == "VIX":
            txt = "—" if v is None else f"{v:.2f}"
        else:
            txt = "—" if v is None else f"{v:,.2f}"
        delta_txt = "" if delta is None else f"{delta:+.2f} 1w"
        trigger_text = f"Trigger: {TRIGGERS.get(n, '')}" if n in TRIGGERS else ""
        return v, lev, delta, txt, delta_txt, trigger_text

ALL_INDICATOR_DATA = {}
def fetch_all_data():
    groups_def = [
        ("Volatility & Market Stress", ["VIX"]),
        ("Credit Stress", ["HY Spread","BB Spread","CCC Spread","Financial Conditions"]),
        ("Rates & Liquidity", ["10Y Treasury","2Y Treasury","10Y-2Y","10Y-3M","SOFR","Fed Funds","M2"]),
        ("Inflation", ["CPI","Core CPI","PPI","10Y Breakeven"]),
        ("Growth & Labor", ["Unemployment","Initial Claims","Continuing Claims","Real GDP","Retail Sales","Industrial Production","Consumer Sentiment"]),
        ("Market Sentiment & Breadth", ["AI/Semiconductor Breadth", "SKEW Index", "High-Beta/Low-Vol Ratio", "Copper/Gold Ratio", "Lumber/Gold Ratio"]),
    ]
    for title, names in groups_def:
        for n in names:
            if n not in ALL_INDICATOR_DATA:
                ALL_INDICATOR_DATA[n] = get_indicator_data(n)
    return groups_def

def risk_score():
    names = ["VIX","HY Spread","BB Spread","CCC Spread","10Y Treasury",
             "10Y-2Y","10Y-3M","10Y Breakeven","Unemployment","Financial Conditions",
             "SKEW Index", "High-Beta/Low-Vol Ratio", "Copper/Gold Ratio", "Lumber/Gold Ratio", "AI/Semiconductor Breadth"]
    vals = {}
    for n in names:
        if n in ALL_INDICATOR_DATA:
            v, lev, _, _, _, _ = ALL_INDICATOR_DATA[n]
            vals[n] = (v, lev)
        else:
            vals[n] = (None, "Normal")
    raw = sum(score_level(l) for _,l in vals.values())
    return min(100, round(raw / (len(names)*3) * 100)), vals

def recession_composite(vals):
    points = 0
    if vals.get("HY Spread", (None,))[0] is not None and vals["HY Spread"][0] >= 5: points += 2
    if vals.get("VIX", (None,))[0] is not None and vals["VIX"][0] >= 30: points += 2
    if vals.get("Unemployment", (None,))[0] is not None and vals["Unemployment"][0] >= 5: points += 2
    if vals.get("10Y-3M", (None,))[0] is not None and vals["10Y-3M"][0] < 0: points += 2
    if vals.get("Financial Conditions", (None,))[0] is not None and vals["Financial Conditions"][0] >= 0.5: points += 2
    return min(10, points)

def color_for(level):
    return {"Normal":"#1f9d55","Watch":"#d99b00","Warning":"#e67e22","Crisis":"#c0392b"}.get(level, "#777")

def generate_dashboard():
    print("Fetching market data...")
    mkt = yfinance_snapshot(list(MARKET_TICKERS.values()))
    
    mkt_cards = []
    for label, ticker in MARKET_TICKERS.items():
        card = market_card(label, mkt.get(ticker))
        if card:
            mkt_cards.append(card)
        else:
            mkt_cards.append({"name": label, "value": "—", "change_pct": "", "status": "Unavailable", "timeframe": ""})

    print("Fetching indicator data...")
    groups_def = fetch_all_data()

    print("Computing risk scores...")
    score, vals = risk_score()
    rec = recession_composite(vals)
    score_label = "NORMAL" if score < 25 else "WATCH" if score < 50 else "WARNING" if score < 75 else "CRISIS"
    
    vix_data = ALL_INDICATOR_DATA.get("VIX", (None, "Normal", None, "—", "", ""))
    vix_v = vix_data[0]
    vix_val = vix_data[3]
    vix_level = vix_data[1]
    
    hy_data = ALL_INDICATOR_DATA.get("HY Spread", (None, "Normal", None, "—", "", ""))
    hy_v = hy_data[0]
    hy_val = hy_data[3]
    hy_level = hy_data[1]

    print("Building indicator grid...")
    grid_groups = []
    for title, names in groups_def:
        indicators = []
        for n in names:
            v, lev, delta, txt, delta_txt, trigger_text = ALL_INDICATOR_DATA[n]
            indicators.append({
                "name": n,
                "desc": DESCRIPTIONS.get(n, ""),
                "val_txt": txt,
                "delta_txt": delta_txt,
                "level": lev,
                "color": color_for(lev),
                "trigger_text": trigger_text
            })
        grid_groups.append({"title": title, "indicators": indicators})

    print("Generating charts...")
    charts_html = []
    # Fixed selection for the static dashboard
    selected_charts = ["VIX", "HY Spread", "10Y-2Y", "Unemployment", "10Y Breakeven"]
    for n in selected_charts:
        df = fred_series(FRED[n][0], 365) # 1 year history
        if df.empty:
            continue
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df.value, mode="lines", name=n, line=dict(color="#2980b9")))
        fig.update_layout(
            height=300, 
            margin=dict(l=10,r=10,t=35,b=10), 
            title=n, 
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)"
        )
        charts_html.append(fig.to_html(full_html=False, include_plotlyjs='cdn' if len(charts_html)==0 else False))

    trigger_rows = [
        {"Indicator": "VIX", "Trigger": ">= 30", "Why": "Volatility regime shift"},
        {"Indicator": "HY Spread", "Trigger": ">= 5%", "Why": "Credit stress"},
        {"Indicator": "CCC Spread", "Trigger": ">= 13%", "Why": "Distressed credit"},
        {"Indicator": "10Y-3M", "Trigger": "< 0%", "Why": "Yield-curve recession signal"},
        {"Indicator": "Unemployment", "Trigger": ">= 5.5%", "Why": "Labor deterioration"},
        {"Indicator": "10Y Breakeven", "Trigger": ">= 3.5%", "Why": "Inflation expectations"},
        {"Indicator": "Financial Conditions", "Trigger": ">= 1.0", "Why": "Tight financial conditions"},
        {"Indicator": "S&P 500", "Trigger": "below 200-day MA by >10%", "Why": "Trend break"},
        {"Indicator": "AI/semiconductor breadth", "Trigger": "multiple leaders below 200DMA", "Why": "AI capex cycle warning"},
        {"Indicator": "Oil", "Trigger": "> $110", "Why": "Stagflation/geopolitical shock"},
    ]

    context = {
        "timestamp": datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z'),
        "FRED_KEY_MISSING": not bool(FRED_KEY),
        "mkt_cards": mkt_cards,
        "score": score,
        "score_label": score_label,
        "score_color": color_for(score_label.title()),
        "rec_score": rec,
        "vix_val": vix_val,
        "vix_level": vix_level,
        "vix_color": color_for(vix_level),
        "hy_val": hy_val,
        "hy_level": hy_level,
        "hy_color": color_for(hy_level),
        "grid_groups": grid_groups,
        "charts": charts_html,
        "trigger_rows": trigger_rows,
        "color_for": color_for
    }

    print("Rendering HTML template...")
    # Create templates dir if it doesn't exist
    os.makedirs("templates", exist_ok=True)
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("dashboard.html")
    output_html = template.render(context)

    with open("market_risk.html", "w", encoding="utf-8") as f:
        f.write(output_html)
        
    print("Done! Dashboard generated at market_risk.html")

if __name__ == "__main__":
    generate_dashboard()
