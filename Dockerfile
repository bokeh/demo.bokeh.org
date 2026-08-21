FROM python:3.14-slim-trixie AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON=3.14t \
    UV_PYTHON_INSTALL_DIR=/opt/python

RUN uv python install --no-bin "$UV_PYTHON"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    apt-get update \
    && apt-get install --yes --no-install-recommends gcc \
    && UV_PYTHON_DOWNLOADS=never uv sync --locked \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.14-slim-trixie

LABEL org.opencontainers.image.authors="Bokeh <info@bokeh.org>"
LABEL org.opencontainers.image.source="https://github.com/bokeh/demo.bokeh.org"

ENV BOKEH_LOG_LEVEL=info \
    BOKEH_RESOURCES=cdn \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 bokeh \
    && useradd --create-home --gid bokeh --uid 10001 bokeh

WORKDIR /app

COPY --from=build /opt/python /opt/python
COPY --from=build /app/.venv /app/.venv

COPY apps ./apps
COPY site ./site
COPY asgi.py catalog.py catalog.toml presentation.py ./

RUN chown -R bokeh:bokeh /app

USER 10001:10001

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHON_GIL=0 \
    UV_PYTHON_DOWNLOADS=never

RUN python -c "import sys, sysconfig; assert sysconfig.get_config_var('Py_GIL_DISABLED') == 1 and not sys._is_gil_enabled()"

EXPOSE 5006

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:5006/healthz', timeout=2).read()"

CMD ["python", "-m", "uvicorn", "asgi:application", \
     "--host", "0.0.0.0", \
     "--port", "5006", \
     "--workers", "1", \
     "--log-level", "info", \
     "--lifespan", "on", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--ws-ping-interval", "20", \
     "--ws-ping-timeout", "20", \
     "--no-server-header"]
