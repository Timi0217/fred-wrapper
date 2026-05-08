import os
from datetime import datetime
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="FRED API Wrapper", version="1.0.0")

# Check for API key at startup
FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    raise RuntimeError("FRED_API_KEY environment variable is required")

FRED_BASE_URL = "https://api.stlouisfed.org/fred"

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
                "api_key": FRED_API_KEY,
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
                "api_key": FRED_API_KEY,
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
                "api_key": FRED_API_KEY,
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
                "api_key": FRED_API_KEY,
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
                "api_key": FRED_API_KEY,
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
