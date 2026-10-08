# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.12.23

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# --- Production dependencies ----------------------------------------------
FROM base AS deps
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# --- Development image (docker compose) -----------------------------------
FROM deps AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# --- Production image ------------------------------------------------------
FROM base AS runtime
# The runtime never installs packages: drop the base image's pip, which also
# removes its vendored copies of urllib3/msgpack/setuptools from the scan surface.
RUN python -m pip uninstall --yes pip \
    && groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=deps /opt/venv /opt/venv
COPY --chown=app:app . .
# collectstatic needs settings to import; these placeholder values exist only
# for this build step and are never used at runtime.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=collectstatic-only \
    DATABASE_URL=postgres://unused@localhost/unused \
    REDIS_URL=redis://localhost:6379/0 \
    JWT_SIGNING_KEYS=unused=unused \
    JWT_ACTIVE_KEY_ID=unused \
    MFA_ENCRYPTION_KEYS=unused \
    python manage.py collectstatic --noinput
USER app
EXPOSE 8000
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
# Request logging is done by the app (structured); gunicorn's access log is off.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--threads", "4", "--worker-class", "gthread", \
     "--max-requests", "2000", "--max-requests-jitter", "200", \
     "--timeout", "30", "--graceful-timeout", "30"]
