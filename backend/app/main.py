from fastapi import FastAPI

from app import health
from app.auth.router import router as auth_router
from app.cameras.router import router as cameras_router
from app.sites.router import router as sites_router
from app.users.router import router as users_router
from app.common.errors import register_error_handlers

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="VisionGuard AI", docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")
    register_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    for r in (sites_router, users_router, cameras_router):
        app.include_router(r, prefix=API_PREFIX)
    return app
