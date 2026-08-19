import re

with open("generate_dashboard.py", "r") as f:
    content = f.read()

# Define the new logic to replace from `def risk_score():` to `print("Generating charts...")`
new_logic = """def get_indicator_data(n):
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

    print("Generating charts...")"""

import re
pattern = re.compile(r"def risk_score\(\):.*?print\(\"Generating charts\.\.\.\"\)", re.DOTALL)
new_content = pattern.sub(new_logic, content)

with open("generate_dashboard.py", "w") as f:
    f.write(new_content)
