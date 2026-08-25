"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, health, index, users
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import AuthContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Codebase-aware assistant API.",
        debug=settings.debug,
    )

    register_exception_handlers(app)

    # Registered BEFORE CORS on purpose. add_middleware inserts at index 0 and the
    # stack is applied reversed, so the last-added middleware is outermost — CORS
    # must be outside this one, or the gate's 403 reaches the browser without CORS
    # headers and the frontend sees an opaque network error.
    app.add_middleware(AuthContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(index.router)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)

    return app


app = create_app()
