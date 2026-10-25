# App server image. Base image and package index come from build args (docker-compose.yml passes them
# from .env, with public defaults):
#   PYTHON_IMAGE      a Python 3.13 image (default python:3.13-slim)
#   UV_DEFAULT_INDEX  the package index (default public PyPI; the internal mirror on work laptops)
ARG PYTHON_IMAGE=python:3.13-slim

# --- Build stage: installs dependencies into /app/.venv. Runs as root so it works
#     whatever the source files' permissions are.
FROM ${PYTHON_IMAGE} AS build
USER root
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
# uv version published before our dependency cut-off date (the registry blocks very new releases)
ARG UV_VERSION=0.12.17
# UV_SYSTEM_CERTS: trust the image's own certificate store (Adyen's internal CA), like pip does
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX} \
    PIP_INDEX_URL=${UV_DEFAULT_INDEX} \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    UV_SYSTEM_CERTS=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN if ! command -v uv >/dev/null 2>&1; then python3 -m pip install --no-cache-dir "uv==${UV_VERSION}"; fi
WORKDIR /app
# Dependencies first (cached unless pyproject.toml changes). uv.lock isn't kept in git: it records the
# index it was made from, which differs between machines. It is made here from UV_DEFAULT_INDEX; the
# exact versions pinned in pyproject.toml make every machine resolve the same packages.
COPY pyproject.toml uv.lock* ./
RUN uv lock && uv sync --locked --no-dev --no-install-project
COPY src ./src
# Database migrations (run by the migrate service: alembic upgrade head)
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --locked --no-dev && chmod -R a+rX /app

# --- Runtime stage: runs as the base image's default non-root user.
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["uvicorn", "--factory", "imcp.app.main:create_app", "--host", "0.0.0.0", "--port", "8787"]
