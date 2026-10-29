FROM ghcr.io/astral-sh/uv:0.11-python3.13-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --group prod

COPY . .
RUN DJANGO_READ_DOT_ENV_FILE=False DJANGO_DEBUG=True \
    /opt/venv/bin/python manage.py collectstatic --noinput


FROM python:3.13-slim-trixie

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_READ_DOT_ENV_FILE=False

RUN useradd --system --uid 1001 --create-home --home-dir /home/appuser appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv
COPY --from=builder --chown=appuser:appuser /app /app
USER appuser

EXPOSE 8000
# Web runs this; Railway overrides the start command for the Celery workers and beat.
CMD ["python", "entrypoint.py"]
