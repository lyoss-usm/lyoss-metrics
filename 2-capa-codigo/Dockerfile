# Imagen del recolector (mvp-ingesta.md, secciones 7 y 12).
# Python 3.12 = version minima de requires-python (>=3.12) en pyproject.toml.

# --- etapa 1: dependencias desde el lockfile congelado, sin grupo dev -------------------------
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- etapa 2: imagen final (sin uv ni cache de instalacion) -------------------------------------
FROM python:3.12-slim
RUN useradd --system --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY collector ./collector
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER app
# Sin argumentos: corrida completa. La configuracion llega por variables de entorno.
ENTRYPOINT ["python", "-m", "collector.main"]
