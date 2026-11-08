from fastapi import FastAPI

from app import health
from app.common.errors import register_error_handlers

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="VisionGuard AI", docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")
    register_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    return app
