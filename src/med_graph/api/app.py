"""FastAPI application exposing the medication graph query layer."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from med_graph.api.routes import router
from med_graph.config import load_target
from med_graph.graph.client import GraphClient, build_driver_from_env

# Vite dev server by default; override for other deployments.
DEFAULT_CORS_ORIGINS = "http://localhost:5173"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Locally this picks .env.local unless MED_GRAPH_ENV says otherwise; on
    # Railway no env files ship, so the injected variables are used as-is.
    print(f"Connecting to {load_target().describe()}")
    driver = build_driver_from_env()
    driver.verify_connectivity()
    app.state.client = GraphClient(driver)
    try:
        yield
    finally:
        driver.close()


def _envelope_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"success": False, "error": message}
    )


def create_app() -> FastAPI:
    app = FastAPI(title="med-graph API", version="0.1.0", lifespan=_lifespan)

    origins = os.environ.get("MED_GRAPH_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in origins if origin.strip()],
        # Vercel gives every preview deployment a fresh subdomain, so those can
        # only be allowed by pattern, e.g. https://med-graph-.*\.vercel\.app
        allow_origin_regex=os.environ.get("MED_GRAPH_CORS_ORIGIN_REGEX"),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Keep every error response in the ApiResponse envelope the frontend expects.
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope_error(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return _envelope_error(422, "Invalid request parameters")

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, __: Exception) -> JSONResponse:
        return _envelope_error(500, "Internal server error")

    app.include_router(router, prefix="/api")
    return app


app = create_app()


def run() -> None:
    """Entry point for the `med-graph-api` script.

    Defaults to localhost for development; a platform that injects HOST/PORT
    (Railway, Fly, Heroku) is honoured so the same command works deployed.
    """
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("med_graph.api.app:app", host=host, port=port, reload=False)
