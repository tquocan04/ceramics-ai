"""Top-level API router. Keep the public surface small (plan §9)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health, order_analysis

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(order_analysis.router)
