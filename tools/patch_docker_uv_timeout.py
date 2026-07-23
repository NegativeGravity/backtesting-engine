from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


class PatchError(RuntimeError):
    pass


OLD = (
    "RUN uv sync --frozen --no-dev --no-editable "
    "--default-index https://pypi.org/simple"
)
NEW = (
    "RUN UV_HTTP_TIMEOUT=300 uv sync --frozen --no-dev --no-editable "
    "--default-index https://pypi.org/simple"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()

    root = args.project_root.resolve()
    dockerfile = root / "Dockerfile"
    if not dockerfile.is_file():
        raise PatchError(f"Dockerfile not found: {dockerfile}")

    text = dockerfile.read_text(encoding="utf-8")
    if NEW in text:
        print("Dockerfile UV timeout is already patched.")
        return 0
    if OLD not in text:
        raise PatchError(
            "Expected uv sync command was not found; Dockerfile was not changed."
        )

    backup = (
        root
        / ".backup"
        / f"dockerfile-uv-timeout-{datetime.now():%Y%m%d-%H%M%S}"
        / "Dockerfile"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dockerfile, backup)

    dockerfile.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"Patched: {dockerfile}")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc
