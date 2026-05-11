import os
from datetime import datetime
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse

app = FastAPI(title="FRED API Wrapper", version="1.0.0")

# Check for API key at startup
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


def get_fred_key() -> str:
    key = FRED_API_KEY or os.environ.get("FRED_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="FRED_API_KEY not configured")
    return key

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
<title>FRED \u2014 Federal Reserve Economic Data</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0a;color:#fff;padding:40px 20px;line-height:1.5}
.container{max-width:640px;margin:0 auto;opacity:0;animation:fadeIn .6s ease forwards}
@keyframes fadeIn{to{opacity:1}}
.card{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:16px;padding:24px;margin-bottom:20px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.title{font-family:'Courier New',monospace;font-size:28px;color:#5B8DB8;font-weight:700}
.health{display:flex;align-items:center;gap:6px;font-size:13px;color:#888}
.health-dot{width:8px;height:8px;background:#0f0;border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.subtitle{color:#888;font-size:15px;margin-bottom:24px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px}
.indicator-card{background:rgba(10,10,10,.5);border-radius:12px;padding:16px;border-left:3px solid;position:relative;animation:slideUp .6s ease backwards}
@keyframes slideUp{from{opacity:0;transform:translateY(10px)}}
.indicator-card:nth-child(1){border-left-color:#5B8DB8;animation-delay:.1s}
.indicator-card:nth-child(2){border-left-color:#4A7CA6;animation-delay:.2s}
.indicator-card:nth-child(3){border-left-color:#6B9DC8;animation-delay:.3s}
.indicator-card:nth-child(4){border-left-color:#3A6B96;animation-delay:.4s}
.indicator-label{font-size:11px;color:#999;text-transform:uppercase;letter-spacing:1px;font-weight:600;margin-bottom:8px}
.indicator-value{font-family:'Courier New',monospace;font-size:44px;color:#fff;font-weight:700;line-height:1}
.indicator-value sub{font-size:20px;color:#ccc;font-weight:400}
.indicator-period{font-size:13px;color:#666;margin-top:6px}
.series-list{list-style:none}
.series-item{padding:12px 0;border-bottom:1px solid rgba(255,255,255,.05);display:flex;justify-content:space-between;align-items:center;font-size:14px}
.series-item:last-child{border-bottom:none}
.series-id{font-family:'Courier New',monospace;color:#5B8DB8;font-weight:600}
.series-meta{color:#666;font-size:13px}
.section-title{font-size:12px;color:#999;text-transform:uppercase;letter-spacing:1px;font-weight:600;margin-bottom:16px}
.form-group{display:flex;gap:8px;margin-bottom:12px}
input{flex:1;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:12px 16px;color:#fff;font-size:14px;outline:none;transition:.2s}
input:focus{border-color:#5B8DB8;background:rgba(255,255,255,.08)}
input::placeholder{color:#666}
button{background:#5B8DB8;color:#fff;border:none;border-radius:8px;padding:12px 24px;font-size:14px;font-weight:600;cursor:pointer;transition:.2s}
button:hover{background:#4A7CA6;transform:translateY(-1px)}
.try-links{font-size:13px;color:#666}
.try-links a{color:#5B8DB8;text-decoration:none;margin:0 2px}
.try-links a:hover{text-decoration:underline}
#result{margin-top:16px;padding:16px;background:rgba(91,141,184,.1);border:1px solid rgba(91,141,184,.3);border-radius:8px;font-family:'Courier New',monospace;font-size:13px;color:#aaa;white-space:pre-wrap;word-wrap:break-word;display:none}
.loading{color:#5B8DB8}
.error{color:#f55}
</style>
</head>
<body>
<div class="container">
<div class="card">
<div class="header">
<h1 class="title">FRED</h1>
<div class="health"><span class="health-dot"></span><span id="health-text">checking...</span></div>
</div>
<p class="subtitle">Federal Reserve Economic Data \u2014 GDP, CPI, unemployment, rates</p>
<div class="grid" id="indicators">
<div class="indicator-card">
<div class="indicator-label">Fed Funds Rate</div>
<div class="indicator-value loading">--<sub>%</sub></div>
<div class="indicator-period">Loading...</div>
</div>
<div class="indicator-card">
<div class="indicator-label">CPI (Year over Year)</div>
<div class="indicator-value loading">--<sub>%</sub></div>
<div class="indicator-period">Loading...</div>
</div>
<div class="indicator-card">
<div class="indicator-label">Unemployment Rate</div>
<div class="indicator-value loading">--<sub>%</sub></div>
<div class="indicator-period">Loading...</div>
</div>
<div class="indicator-card">
<div class="indicator-label">Real GDP Growth</div>
<div class="indicator-value loading">--<sub>%</sub></div>
<div class="indicator-period">Loading...</div>
</div>
</div>
</div>
<div class="card" style="animation:slideUp .6s .5s ease backwards">
<div class="section-title">Popular Series</div>
<ul class="series-list">
<li class="series-item"><span class="series-id">FEDFUNDS</span><span class="series-meta">Monthly \u00b7 since 1954</span></li>
<li class="series-item"><span class="series-id">CPIAUCSL</span><span class="series-meta">Monthly \u00b7 since 1947</span></li>
<li class="series-item"><span class="series-id">UNRATE</span><span class="series-meta">Monthly \u00b7 since 1948</span></li>
<li class="series-item"><span class="series-id">GDP</span><span class="series-meta">Quarterly \u00b7 since 1947</span></li>
<li class="series-item"><span class="series-id">DGS10</span><span class="series-meta">Daily \u00b7 since 1962</span></li>
</ul>
</div>
<div class="card" style="animation:slideUp .6s .6s ease backwards">
<form id="seriesForm" class="form-group">
<input type="text" id="seriesInput" placeholder="GDP" required>
<button type="submit">\u2192 series</button>
</form>
<div class="try-links">Try: <a href="#" data-series="FEDFUNDS">FEDFUNDS</a> \u00b7 <a href="#" data-series="CPIAUCSL">CPIAUCSL</a> \u00b7 <a href="#" data-series="UNRATE">UNRATE</a> \u00b7 <a href="#" data-series="DGS10">DGS10</a></div>
<div id="result"></div>
</div>
</div>
<script>
const indicators=[
{name:'fed_funds_rate',idx:0,label:'FED FUNDS RATE'},
{name:'cpi',idx:1,label:'CPI (YEAR OVER YEAR)'},
{name:'unemployment',idx:2,label:'UNEMPLOYMENT RATE'},
{name:'gdp',idx:3,label:'REAL GDP GROWTH'}
];
async function fetchHealth(){
const start=Date.now();
try{
const res=await fetch('/health');
const data=await res.json();
const ms=Date.now()-start;
document.getElementById('health-text').textContent='online \u00b7 '+ms+'ms';
}catch(e){
document.getElementById('health-text').textContent='offline';
document.querySelector('.health-dot').style.background='#f55';
}
}
async function fetchIndicator(ind){
try{
const res=await fetch('/indicator?name='+ind.name);
const data=await res.json();
const card=document.querySelectorAll('.indicator-card')[ind.idx];
const valueEl=card.querySelector('.indicator-value');
const periodEl=card.querySelector('.indicator-period');
if(data.observations && data.observations.length>0){
const latest=data.observations[0];
const val=parseFloat(latest.value);
const date=new Date(latest.date);
const monthNames=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const month=monthNames[date.getMonth()];
const year=date.getFullYear();
let period=month+' '+year;
if(data.frequency==='Quarterly'){
const q=Math.floor(date.getMonth()/3)+1;
period='Q'+q+' '+year;
}
valueEl.innerHTML=val.toFixed(1)+'<sub>%</sub>';
valueEl.classList.remove('loading');
periodEl.textContent=period;
}else{
valueEl.innerHTML='--<sub>%</sub>';
valueEl.classList.remove('loading');
periodEl.textContent='No data';
}
}catch(e){
const card=document.querySelectorAll('.indicator-card')[ind.idx];
const valueEl=card.querySelector('.indicator-value');
const periodEl=card.querySelector('.indicator-period');
valueEl.innerHTML='--<sub>%</sub>';
valueEl.classList.remove('loading');
valueEl.classList.add('error');
periodEl.textContent='Error';
}
}
async function fetchSeries(seriesId){
const resultDiv=document.getElementById('result');
resultDiv.style.display='block';
resultDiv.textContent='Loading...';
resultDiv.className='loading';
try{
const res=await fetch('/series?series_id='+encodeURIComponent(seriesId));
if(!res.ok){
const err=await res.json();
resultDiv.textContent='Error: '+(err.detail||'Unknown error');
resultDiv.className='error';
return;
}
const data=await res.json();
resultDiv.textContent=JSON.stringify(data,null,2);
resultDiv.className='';
}catch(e){
resultDiv.textContent='Error: '+e.message;
resultDiv.className='error';
}
}
document.getElementById('seriesForm').addEventListener('submit',function(e){
e.preventDefault();
const seriesId=document.getElementById('seriesInput').value.trim();
if(seriesId)fetchSeries(seriesId);
});
document.querySelectorAll('.try-links a').forEach(link=>{
link.addEventListener('click',function(e){
e.preventDefault();
const seriesId=this.getAttribute('data-series');
document.getElementById('seriesInput').value=seriesId;
fetchSeries(seriesId);
});
});
fetchHealth();
async function loadIndicators(){for(const ind of indicators){await fetchIndicator(ind);await new Promise(r=>setTimeout(r,300))}}
loadIndicators();
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
