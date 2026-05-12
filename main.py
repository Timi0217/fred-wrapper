import os
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse


# Check for API key at startup
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
http_client: Optional[httpx.AsyncClient] = None

# ── Dashboard cache ──────────────────────────────────────────────────────
_dashboard_data: dict = {"indicators": [], "status": "warming_up"}
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 3600  # 1 hour


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: dict):
    _cache[key] = (time.time(), value)

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


def get_fred_key() -> str:
    key = FRED_API_KEY or os.environ.get("FRED_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="FRED_API_KEY not configured")
    return key


async def _bg_fetch_obs(series_id: str, limit: int = 1) -> list:
    """Fetch observations for a series in background task."""
    key = FRED_API_KEY or os.environ.get("FRED_API_KEY", "")
    if not key:
        return []
    try:
        resp = await http_client.get(
            f"{FRED_BASE_URL}/series/observations",
            params={
                "series_id": series_id,
                "api_key": key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("observations", [])
    except Exception:
        pass
    return []


async def _refresh_dashboard():
    """Background task: computes dashboard values on startup, then every 2 hours."""
    global _dashboard_data
    await asyncio.sleep(3)

    while True:
        prev = _dashboard_data.get("indicators", [])
        prev_map = {ind["name"]: ind for ind in prev if isinstance(ind, dict)}
        results = []

        # 1) Fed Funds Rate — FEDFUNDS — already a percentage
        entry = prev_map.get("fed_funds_rate", {})
        obs = await _bg_fetch_obs("FEDFUNDS", 1)
        if obs and obs[0].get("value", ".") != ".":
            val = float(obs[0]["value"])
            entry = {
                "name": "fed_funds_rate",
                "label": "FED FUNDS RATE",
                "value": round(val, 2),
                "unit": "%",
                "date": obs[0].get("date"),
                "direction": None,
            }
        results.append(entry if entry else {"name": "fed_funds_rate", "label": "FED FUNDS RATE", "value": None})

        await asyncio.sleep(1)

        # 2) CPI Year-over-Year — compute from CPIAUCSL (need 13 months)
        entry = prev_map.get("cpi_yoy", {})
        obs = await _bg_fetch_obs("CPIAUCSL", 13)
        if len(obs) >= 13:
            try:
                current = float(obs[0]["value"])
                year_ago = float(obs[12]["value"])
                yoy = ((current - year_ago) / year_ago) * 100
                entry = {
                    "name": "cpi_yoy",
                    "label": "CPI INFLATION",
                    "value": round(yoy, 1),
                    "unit": "% YoY",
                    "date": obs[0].get("date"),
                    "direction": "up" if yoy > 2.0 else "down" if yoy < 1.0 else "neutral",
                }
            except (ValueError, ZeroDivisionError):
                pass
        results.append(entry if entry else {"name": "cpi_yoy", "label": "CPI INFLATION", "value": None})

        await asyncio.sleep(1)

        # 3) Unemployment Rate — UNRATE — already a percentage
        entry = prev_map.get("unemployment", {})
        obs = await _bg_fetch_obs("UNRATE", 2)
        if obs and obs[0].get("value", ".") != ".":
            val = float(obs[0]["value"])
            prev_val = float(obs[1]["value"]) if len(obs) > 1 and obs[1].get("value", ".") != "." else None
            entry = {
                "name": "unemployment",
                "label": "UNEMPLOYMENT",
                "value": round(val, 1),
                "unit": "%",
                "date": obs[0].get("date"),
                "direction": ("up" if prev_val and val > prev_val else "down" if prev_val and val < prev_val else "neutral") if prev_val else None,
                "previous": round(prev_val, 1) if prev_val else None,
            }
        results.append(entry if entry else {"name": "unemployment", "label": "UNEMPLOYMENT", "value": None})

        await asyncio.sleep(1)

        # 4) Real GDP Growth — A191RL1Q225SBEA — already a percentage (annualized quarterly)
        entry = prev_map.get("gdp_growth", {})
        obs = await _bg_fetch_obs("A191RL1Q225SBEA", 2)
        if obs and obs[0].get("value", ".") != ".":
            val = float(obs[0]["value"])
            prev_val = float(obs[1]["value"]) if len(obs) > 1 and obs[1].get("value", ".") != "." else None
            entry = {
                "name": "gdp_growth",
                "label": "GDP GROWTH",
                "value": round(val, 1),
                "unit": "% QoQ",
                "date": obs[0].get("date"),
                "direction": ("up" if prev_val and val > prev_val else "down" if prev_val and val < prev_val else "neutral") if prev_val else None,
                "previous": round(prev_val, 1) if prev_val else None,
            }
        results.append(entry if entry else {"name": "gdp_growth", "label": "GDP GROWTH", "value": None})

        await asyncio.sleep(1)

        # 5) 10-Year Treasury — DGS10
        entry = prev_map.get("treasury_10y", {})
        obs = await _bg_fetch_obs("DGS10", 5)
        valid = [o for o in obs if o.get("value", ".") != "."]
        if valid:
            val = float(valid[0]["value"])
            prev_val = float(valid[1]["value"]) if len(valid) > 1 else None
            entry = {
                "name": "treasury_10y",
                "label": "10Y TREASURY",
                "value": round(val, 2),
                "unit": "%",
                "date": valid[0].get("date"),
                "direction": ("up" if prev_val and val > prev_val else "down" if prev_val and val < prev_val else "neutral") if prev_val else None,
            }
        results.append(entry if entry else {"name": "treasury_10y", "label": "10Y TREASURY", "value": None})

        await asyncio.sleep(1)

        # 6) 30Y Mortgage Rate — MORTGAGE30US
        entry = prev_map.get("mortgage_30y", {})
        obs = await _bg_fetch_obs("MORTGAGE30US", 5)
        valid = [o for o in obs if o.get("value", ".") != "."]
        if valid:
            val = float(valid[0]["value"])
            prev_val = float(valid[1]["value"]) if len(valid) > 1 else None
            entry = {
                "name": "mortgage_30y",
                "label": "30Y MORTGAGE",
                "value": round(val, 2),
                "unit": "%",
                "date": valid[0].get("date"),
                "direction": ("up" if prev_val and val > prev_val else "down" if prev_val and val < prev_val else "neutral") if prev_val else None,
            }
        results.append(entry if entry else {"name": "mortgage_30y", "label": "30Y MORTGAGE", "value": None})

        _dashboard_data["indicators"] = results
        _dashboard_data["status"] = "ready"
        _dashboard_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        _cache_set("dashboard", _dashboard_data)

        await asyncio.sleep(7200)  # Refresh every 2 hours


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=15.0)
    task = asyncio.create_task(_refresh_dashboard())
    yield
    task.cancel()
    await http_client.aclose()


app = FastAPI(title="FRED API Wrapper", version="1.0.0", lifespan=lifespan)

# Indicator name to FRED series ID mapping
INDICATOR_MAPPING = {
    "inflation": "CPIAUCSL",
    "gdp": "GDP",
    "unemployment": "UNRATE",
    "fed_funds_rate": "FEDFUNDS",
    "interest_rate": "FEDFUNDS",
    "cpi": "CPIAUCSL",
    "pce": "PCEPI",
    "core_cpi": "CPILFESL",
    "housing_starts": "HOUST",
    "retail_sales": "RSAFS",
    "industrial_production": "INDPRO",
    "consumer_confidence": "UMCSENT",
    "ppi": "PPIACO",
    "m2": "M2SL",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "treasury_30y": "DGS30",
    "mortgage_rate": "MORTGAGE30US",
    "sp500": "SP500",
    "wage_growth": "CES0500000003",
    "labor_force": "CLF16OV",
    "nonfarm_payrolls": "PAYEMS",
    "initial_claims": "ICSA",
    "trade_balance": "BOPGSTB",
    "oil_price": "DCOILWTICO",
    "gold_price": "GOLDAMGBD228NLBM",
}

HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FRED &mdash; Federal Reserve Economic Data</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e8e8e8;padding:40px 20px;line-height:1.5}
.container{max-width:680px;margin:0 auto;opacity:0;animation:fadeIn .5s ease forwards}
@keyframes fadeIn{to{opacity:1}}
@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

/* Header */
.header-card{background:linear-gradient(135deg,rgba(30,58,82,.4),rgba(20,40,60,.2));border:1px solid rgba(91,141,184,.15);border-radius:20px;padding:28px 28px 0;margin-bottom:16px;overflow:hidden}
.header-row{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
.brand{display:flex;align-items:center;gap:12px}
.brand-icon{width:42px;height:42px;background:linear-gradient(135deg,#5B8DB8,#3A6B96);border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:'Courier New',monospace;font-weight:900;font-size:16px;color:#fff;letter-spacing:-1px}
.brand-text .title{font-size:22px;font-weight:700;color:#fff;letter-spacing:-.5px}
.brand-text .org{font-size:12px;color:rgba(91,141,184,.8);font-weight:500;letter-spacing:.5px}
.health-badge{display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:6px 14px;font-size:12px;color:#888;backdrop-filter:blur(10px)}
.health-dot{width:7px;height:7px;background:#555;border-radius:50%;transition:background .3s}
.health-dot.on{background:#4CAF50;box-shadow:0 0 8px rgba(76,175,80,.4)}
.tagline{color:#888;font-size:14px;margin-bottom:20px;margin-left:54px}

/* Indicator grid */
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;background:rgba(255,255,255,.04);border-radius:0 0 20px 20px;overflow:hidden;margin:0 -28px}
.ind{background:#0a0a0a;padding:20px;text-align:center;position:relative;transition:background .2s}
.ind:hover{background:rgba(91,141,184,.04)}
.ind-label{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:1.2px;font-weight:600;margin-bottom:10px}
.ind-val{font-family:'Courier New',monospace;font-size:28px;font-weight:700;color:#fff;line-height:1;margin-bottom:2px}
.ind-unit{font-size:13px;color:#555;font-weight:400}
.ind-meta{font-size:11px;color:#555;margin-top:8px;display:flex;align-items:center;justify-content:center;gap:4px}
.arrow{font-size:10px;display:inline-block}
.arrow.up{color:#4CAF50}
.arrow.down{color:#ef5350}
.ind.warm .ind-val{color:#555;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:.6}50%{opacity:.3}}

/* Secondary cards */
.card{background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:20px 24px;margin-bottom:12px;animation:slideUp .5s ease backwards}

/* Series list */
.series-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.series-chip{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:10px;cursor:pointer;transition:all .2s}
.series-chip:hover{background:rgba(91,141,184,.08);border-color:rgba(91,141,184,.2)}
.series-chip .id{font-family:'Courier New',monospace;font-size:13px;color:#5B8DB8;font-weight:600}
.series-chip .freq{font-size:11px;color:#555}

/* Search */
.search-row{display:flex;gap:8px;margin-bottom:10px}
.search-input{flex:1;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:11px 16px;color:#fff;font-size:14px;outline:none;transition:all .2s}
.search-input:focus{border-color:rgba(91,141,184,.5);background:rgba(255,255,255,.06);box-shadow:0 0 0 3px rgba(91,141,184,.1)}
.search-input::placeholder{color:#444}
.search-btn{background:linear-gradient(135deg,#5B8DB8,#4A7CA6);color:#fff;border:none;border-radius:10px;padding:11px 20px;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;white-space:nowrap}
.search-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(91,141,184,.3)}
.quick-links{display:flex;gap:6px;flex-wrap:wrap}
.quick-link{background:rgba(255,255,255,.04);color:#666;padding:5px 10px;border-radius:6px;font-size:11px;cursor:pointer;transition:all .15s;border:1px solid transparent;font-family:'Courier New',monospace}
.quick-link:hover{background:rgba(91,141,184,.1);color:#5B8DB8;border-color:rgba(91,141,184,.2)}
#result{margin-top:14px;padding:14px;background:rgba(91,141,184,.06);border:1px solid rgba(91,141,184,.15);border-radius:10px;font-family:'Courier New',monospace;font-size:12px;color:#999;white-space:pre-wrap;word-wrap:break-word;display:none;max-height:300px;overflow-y:auto}
.section-label{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;margin-bottom:12px}
</style>
</head>
<body>
<div class="container">

<div class="header-card">
<div class="header-row">
<div class="brand">
<div class="brand-icon">F</div>
<div class="brand-text">
<div class="title">FRED</div>
<div class="org">Federal Reserve Economic Data</div>
</div>
</div>
<div class="health-badge"><span class="health-dot" id="dot"></span><span id="health-text">checking...</span></div>
</div>
<div class="tagline">Macro indicators, interest rates, inflation &amp; employment</div>
<div class="grid" id="grid"></div>
</div>

<div class="card" style="animation-delay:.15s">
<div class="section-label">Popular Series</div>
<div class="series-grid" id="seriesGrid">
<div class="series-chip" onclick="doSearch('FEDFUNDS')"><span class="id">FEDFUNDS</span><span class="freq">Monthly</span></div>
<div class="series-chip" onclick="doSearch('CPIAUCSL')"><span class="id">CPIAUCSL</span><span class="freq">Monthly</span></div>
<div class="series-chip" onclick="doSearch('UNRATE')"><span class="id">UNRATE</span><span class="freq">Monthly</span></div>
<div class="series-chip" onclick="doSearch('DGS10')"><span class="id">DGS10</span><span class="freq">Daily</span></div>
<div class="series-chip" onclick="doSearch('GDP')"><span class="id">GDP</span><span class="freq">Quarterly</span></div>
<div class="series-chip" onclick="doSearch('MORTGAGE30US')"><span class="id">MORTGAGE30US</span><span class="freq">Weekly</span></div>
</div>
</div>

<div class="card" style="animation-delay:.25s">
<div class="search-row">
<input type="text" class="search-input" id="searchInput" placeholder="Enter series ID (e.g. GDP, CPIAUCSL)" required>
<button class="search-btn" onclick="doSearch()">Fetch &rarr;</button>
</div>
<div class="quick-links">
<span style="color:#444;font-size:11px;margin-right:2px">Try:</span>
<span class="quick-link" onclick="doSearch('FEDFUNDS')">FEDFUNDS</span>
<span class="quick-link" onclick="doSearch('SP500')">SP500</span>
<span class="quick-link" onclick="doSearch('DCOILWTICO')">OIL</span>
<span class="quick-link" onclick="doSearch('ICSA')">JOBLESS</span>
<span class="quick-link" onclick="doSearch('M2SL')">M2</span>
</div>
<div id="result"></div>
</div>

</div>

<script>
const M=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function renderGrid(inds, warming) {
  const g = document.getElementById('grid');
  if (!inds || !inds.length) {
    g.innerHTML = Array(6).fill('<div class="ind warm"><div class="ind-label">\u2014</div><div class="ind-val">\u2014</div><div class="ind-meta">Loading...</div></div>').join('');
    return;
  }
  g.innerHTML = inds.map(function(ind) {
    if (!ind.value && ind.value !== 0) {
      return '<div class="ind' + (warming ? ' warm' : '') + '"><div class="ind-label">' + (ind.label || '\u2014') + '</div><div class="ind-val">\u2014</div><div class="ind-meta">' + (warming ? 'Loading...' : 'No data') + '</div></div>';
    }
    var val = typeof ind.value === 'number' ? ind.value : parseFloat(ind.value);
    var display = Math.abs(val) >= 10 ? val.toFixed(1) : val.toFixed(2);
    var unit = ind.unit || '%';
    var arrow = '';
    if (ind.direction === 'up') arrow = '<span class="arrow up">\u25B2</span>';
    else if (ind.direction === 'down') arrow = '<span class="arrow down">\u25BC</span>';
    var period = '';
    if (ind.date) {
      var d = new Date(ind.date + 'T00:00:00');
      var m = M[d.getMonth()];
      var y = d.getFullYear();
      if (ind.name === 'gdp_growth') {
        var q = Math.floor(d.getMonth() / 3) + 1;
        period = 'Q' + q + ' ' + y;
      } else {
        period = m + ' ' + y;
      }
    }
    var prev = '';
    if (ind.previous != null && ind.direction) {
      prev = ' \u00b7 prev ' + ind.previous;
    }
    return '<div class="ind"><div class="ind-label">' + ind.label + '</div><div class="ind-val">' + display + '<span class="ind-unit"> ' + unit + '</span></div><div class="ind-meta">' + arrow + period + prev + '</div></div>';
  }).join('');
}

async function init() {
  // Health check
  var t0 = Date.now();
  try {
    await fetch('/health');
    var ms = Date.now() - t0;
    document.getElementById('dot').classList.add('on');
    document.getElementById('health-text').textContent = 'online \u00b7 ' + ms + 'ms';
  } catch(e) {
    document.getElementById('health-text').textContent = 'offline';
  }

  // Dashboard data
  try {
    var dash = await fetch('/dashboard').then(function(r) { return r.json(); });
    var warming = dash.status === 'warming_up';
    renderGrid(dash.indicators || [], warming);
    if (warming) {
      var poll = setInterval(async function() {
        try {
          var d2 = await fetch('/dashboard').then(function(r) { return r.json(); });
          renderGrid(d2.indicators || [], d2.status === 'warming_up');
          if (d2.status === 'ready') clearInterval(poll);
        } catch(e) { clearInterval(poll); }
      }, 8000);
    }
  } catch(e) {
    renderGrid([], false);
  }
}

async function doSearch(seriesId) {
  if (!seriesId) {
    seriesId = document.getElementById('searchInput').value.trim().toUpperCase();
  }
  if (!seriesId) return;
  document.getElementById('searchInput').value = seriesId;
  var resultDiv = document.getElementById('result');
  resultDiv.style.display = 'block';
  resultDiv.style.color = '#5B8DB8';
  resultDiv.textContent = 'Loading ' + seriesId + '...';
  try {
    var res = await fetch('/series?series_id=' + encodeURIComponent(seriesId));
    if (!res.ok) {
      var err = await res.json();
      resultDiv.style.color = '#ef5350';
      resultDiv.textContent = 'Error: ' + (err.detail || 'Unknown error');
      return;
    }
    var data = await res.json();
    resultDiv.style.color = '#999';
    resultDiv.textContent = JSON.stringify(data, null, 2);
  } catch(e) {
    resultDiv.style.color = '#ef5350';
    resultDiv.textContent = 'Error: ' + e.message;
  }
}

document.getElementById('searchInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); doSearch(); }
});

init();
</script>
</body>
</html>"""


@app.get("/")
async def root():
    """Rich HTML home page with live FRED data"""
    return HTMLResponse(content=HOME_HTML)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.get("/dashboard")
async def dashboard():
    """Returns pre-fetched dashboard data instantly. Data is refreshed every 2 hours
    by a background task — no blocking upstream calls on this endpoint."""
    return _dashboard_data


@app.get("/series")
async def get_series(series_id: str = Query(..., description="FRED series ID (e.g., GDP, CPIAUCSL)")):
    """Get a specific economic data series with metadata and recent observations"""
    timestamp = datetime.utcnow().isoformat() + "Z"

    async with httpx.AsyncClient() as client:
        try:
            # Get series metadata
            metadata_params = {
                "series_id": series_id,
                "api_key": get_fred_key(),
                "file_type": "json"
            }
            metadata_response = await client.get(
                f"{FRED_BASE_URL}/series",
                params=metadata_params,
                timeout=10.0
            )

            if metadata_response.status_code == 400:
                raise HTTPException(status_code=400, detail="Invalid series ID or bad request")

            metadata_response.raise_for_status()
            metadata_data = metadata_response.json()

            # Check if series exists
            if "seriess" not in metadata_data or len(metadata_data["seriess"]) == 0:
                raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found")

            series_info = metadata_data["seriess"][0]

            # Get series observations
            obs_params = {
                "series_id": series_id,
                "api_key": get_fred_key(),
                "file_type": "json",
                "sort_order": "desc",
                "limit": 10
            }
            obs_response = await client.get(
                f"{FRED_BASE_URL}/series/observations",
                params=obs_params,
                timeout=10.0
            )

            if obs_response.status_code == 400:
                raise HTTPException(status_code=400, detail="Invalid request parameters")

            obs_response.raise_for_status()
            obs_data = obs_response.json()

            # Format observations
            observations = []
            if "observations" in obs_data:
                for obs in obs_data["observations"]:
                    observations.append({
                        "date": obs.get("date"),
                        "value": obs.get("value")
                    })

            return {
                "series_id": series_info.get("id"),
                "title": series_info.get("title"),
                "frequency": series_info.get("frequency"),
                "units": series_info.get("units"),
                "seasonal_adjustment": series_info.get("seasonal_adjustment"),
                "observations": observations,
                "timestamp": timestamp
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                raise HTTPException(status_code=400, detail="Bad request to FRED API")
            elif e.response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found")
            else:
                raise HTTPException(status_code=503, detail="FRED API unavailable")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="FRED API unavailable")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/indicator")
async def get_indicator(name: str = Query(..., description="Indicator name (e.g., inflation, gdp, unemployment)")):
    """Convenience endpoint that maps common indicator names to FRED series IDs"""
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Normalize the name to lowercase
    normalized_name = name.lower().strip()

    # Check if indicator exists in mapping
    if normalized_name not in INDICATOR_MAPPING:
        available_indicators = sorted(INDICATOR_MAPPING.keys())
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Indicator '{name}' not found",
                "available_indicators": available_indicators,
                "timestamp": timestamp
            }
        )

    # Get the series ID for this indicator
    series_id = INDICATOR_MAPPING[normalized_name]

    # Call the series endpoint logic
    async with httpx.AsyncClient() as client:
        try:
            # Get series metadata
            metadata_params = {
                "series_id": series_id,
                "api_key": get_fred_key(),
                "file_type": "json"
            }
            metadata_response = await client.get(
                f"{FRED_BASE_URL}/series",
                params=metadata_params,
                timeout=10.0
            )

            if metadata_response.status_code == 400:
                raise HTTPException(status_code=400, detail="Invalid series ID or bad request")

            metadata_response.raise_for_status()
            metadata_data = metadata_response.json()

            # Check if series exists
            if "seriess" not in metadata_data or len(metadata_data["seriess"]) == 0:
                raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found")

            series_info = metadata_data["seriess"][0]

            # Get series observations
            obs_params = {
                "series_id": series_id,
                "api_key": get_fred_key(),
                "file_type": "json",
                "sort_order": "desc",
                "limit": 10
            }
            obs_response = await client.get(
                f"{FRED_BASE_URL}/series/observations",
                params=obs_params,
                timeout=10.0
            )

            if obs_response.status_code == 400:
                raise HTTPException(status_code=400, detail="Invalid request parameters")

            obs_response.raise_for_status()
            obs_data = obs_response.json()

            # Format observations
            observations = []
            if "observations" in obs_data:
                for obs in obs_data["observations"]:
                    observations.append({
                        "date": obs.get("date"),
                        "value": obs.get("value")
                    })

            return {
                "indicator_name": normalized_name,
                "series_id": series_info.get("id"),
                "title": series_info.get("title"),
                "frequency": series_info.get("frequency"),
                "units": series_info.get("units"),
                "seasonal_adjustment": series_info.get("seasonal_adjustment"),
                "observations": observations,
                "timestamp": timestamp
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                raise HTTPException(status_code=400, detail="Bad request to FRED API")
            elif e.response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found")
            else:
                raise HTTPException(status_code=503, detail="FRED API unavailable")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="FRED API unavailable")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/search")
async def search_series(query: str = Query(..., description="Search query (e.g., 'inflation', 'employment')")):
    """Search FRED series by text query"""
    timestamp = datetime.utcnow().isoformat() + "Z"

    async with httpx.AsyncClient() as client:
        try:
            # Search FRED series
            search_params = {
                "search_text": query,
                "api_key": get_fred_key(),
                "file_type": "json",
                "limit": 10
            }
            search_response = await client.get(
                f"{FRED_BASE_URL}/series/search",
                params=search_params,
                timeout=10.0
            )

            if search_response.status_code == 400:
                raise HTTPException(status_code=400, detail="Invalid search query or bad request")

            search_response.raise_for_status()
            search_data = search_response.json()

            # Format results
            results = []
            if "seriess" in search_data:
                for series in search_data["seriess"]:
                    results.append({
                        "series_id": series.get("id"),
                        "title": series.get("title"),
                        "frequency": series.get("frequency"),
                        "units": series.get("units"),
                        "popularity": series.get("popularity"),
                        "last_updated": series.get("last_updated")
                    })

            return {
                "query": query,
                "results": results,
                "count": len(results),
                "timestamp": timestamp
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                raise HTTPException(status_code=400, detail="Bad request to FRED API")
            else:
                raise HTTPException(status_code=503, detail="FRED API unavailable")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="FRED API unavailable")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
