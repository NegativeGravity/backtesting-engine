from pathlib import Path

from fastapi import FastAPI

from vex_replay.builder import ReplayBundleBuilder
from vex_replay.repository import ReplayRunRepository
from vex_replay.session import ReplaySession


def create_app(project_root: str | Path | None = None) -> FastAPI:
    from vex_replay.api import create_app as build_app

    return build_app(project_root)


__all__ = [
    "ReplayBundleBuilder",
    "ReplayRunRepository",
    "ReplaySession",
    "create_app",
]
