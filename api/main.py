"""AI Opportunity Radar — FastAPI application."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import customers, opportunities, scan

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

app.include_router(opportunities.router)
app.include_router(customers.router)
app.include_router(scan.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "opportunity-radar"}


@app.get("/")
async def root():
    return {
        "service": "AI Opportunity Radar",
        "docs": "/docs",
        "version": "1.0.0",
    }
