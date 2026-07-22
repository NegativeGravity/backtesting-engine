FROM public.ecr.aws/docker/library/node:22-alpine AS dashboard-build
WORKDIR /build/apps/dashboard_web
COPY apps/dashboard_web/package.json apps/dashboard_web/package-lock.json apps/dashboard_web/.npmrc ./
RUN npm ci
COPY apps/dashboard_web ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.10.0 AS uv

FROM public.ecr.aws/docker/library/python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_DEFAULT_INDEX=https://pypi.org/simple
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:/app/strategies"
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --default-index https://pypi.org/simple
COPY apps ./apps
COPY --from=dashboard-build /build/apps/dashboard_web/dist ./apps/dashboard_web/dist
COPY examples ./examples
COPY schemas ./schemas
COPY scripts ./scripts
COPY docs ./docs
COPY strategies ./strategies
RUN mkdir -p /app/data/cache /app/data/replay /app/data/live-runs /app/data/mt5
EXPOSE 8000 8001
CMD ["vex-engine", "--project-root", "/app", "--host", "0.0.0.0", "--port", "8001"]
