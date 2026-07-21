from pathlib import Path

from fastapi import FastAPI


def create_app(
    project_root: str | Path | None = None,
    engine_url: str | None = None,
) -> FastAPI:
    from vex_dashboard.api import create_app as build_app

    return build_app(project_root, engine_url)


__all__ = ["create_app"]
