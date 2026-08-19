# Market Crash Dashboard

A self-hostable Streamlit dashboard for monitoring market-crash early-warning signals.

## What it monitors

- S&P 500, Nasdaq 100, Dow, Russell 2000
- VIX
- High-yield OAS
- BB and CCC/lower credit spreads
- 10Y and 2Y Treasury yields
- 10Y-2Y and 10Y-3M curves
- 10Y inflation breakeven
- Unemployment
- Initial and continuing claims
- Chicago Fed Financial Conditions Index
- CPI / Core CPI / PPI
- Fed Funds / SOFR
- Real GDP
- Retail sales
- Industrial production
- Consumer sentiment
- M2
- Transparent crash-trigger matrix

## Data providers

FRED provides the macroeconomic series. FRED's official API exposes series observations through `fred/series/observations` and requires an API key.

For intraday index values, this project uses Massive's index snapshot API. Massive documents real-time index snapshots and identifies whether returned data are REAL-TIME or DELAYED.

### Environment variables

Create `.env` or configure these in your hosting provider:

FRED_API_KEY=your_fred_key
MASSIVE_API_KEY=your_massive_key
REFRESH_SECONDS=300

Do not put API keys in frontend JavaScript.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export FRED_API_KEY="..."
export MASSIVE_API_KEY="..."
streamlit run app.py
```

Windows PowerShell:

```powershell
$env:FRED_API_KEY="..."
$env:MASSIVE_API_KEY="..."
streamlit run app.py
```

## Hosting

### Streamlit Community Cloud
1. Put `app.py` and `requirements.txt` in a GitHub repository.
2. Deploy the app.
3. Add `FRED_API_KEY` and `MASSIVE_API_KEY` under app Secrets.
4. Set the app to public/private as appropriate.

### Your own VPS
Run:

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Put Nginx/Caddy in front of it and enable HTTPS.

## Important

"Real time" depends on the market-data entitlement. FRED macroeconomic data are release-based, not tick-by-tick. Massive's documentation distinguishes REAL-TIME and DELAYED index data.

The Crash Risk Score is a transparent rules-based stress score, not a calibrated probability of a >50% crash. Thresholds should be backtested before being used for automated trading decisions.
