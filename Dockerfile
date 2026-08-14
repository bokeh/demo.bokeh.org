FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

LABEL org.opencontainers.image.authors="Bokeh <info@bokeh.org>"
LABEL org.opencontainers.image.source="https://github.com/bokeh/demo.bokeh.org"

ENV BOKEH_LOG_LEVEL=info \
    BOKEH_RESOURCES=cdn \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

RUN groupadd --gid 10001 bokeh \
    && useradd --create-home --gid bokeh --uid 10001 bokeh

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

COPY apps ./apps
COPY site ./site
COPY asgi.py catalog.py presentation.py ./

RUN chown -R bokeh:bokeh /app

USER 10001:10001

ENV PATH="/app/.venv/bin:$PATH"

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
