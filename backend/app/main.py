from fastapi import FastAPI

from app import health

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="VisionGuard AI", docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")
    app.include_router(health.router, prefix=API_PREFIX)
    return app
