"""AI Opportunity Radar — FastAPI application."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routers import customers, opportunities, scan
from billing import webhooks as billing_webhooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

app = FastAPI(
    title="AI Opportunity Radar API",
    description="B2B buying intent signal detection for AI automation agencies.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "https://your-dashboard.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = uuid.uuid4().hex[:8]
    start = time.time()
    response = await call_next(request)
    ms = round((time.time() - start) * 1000)
    import logging
    logging.getLogger("radar.http").info(
        "%s %s -> %s (%dms) [%s]",
        request.method, request.url.path, response.status_code, ms, req_id
    )
    response.headers["X-Request-Id"] = req_id
    return response


app.include_router(opportunities.router)
app.include_router(customers.router)
app.include_router(scan.router)
app.include_router(billing_webhooks.router)


@app.get("/health")
async def health():
    import subprocess
    try:
        agy = subprocess.run(["agy.exe", "--help"], capture_output=True, timeout=3)
        agy_ok = agy.returncode == 0
    except Exception:
        agy_ok = False
    return {
        "status": "ok",
        "service": "opportunity-radar",
        "agy_worker": "available" if agy_ok else "unavailable",
    }


@app.get("/")
async def root():
    return {
        "service": "AI Opportunity Radar",
        "docs": "/docs",
        "version": "1.0.0",
    }
