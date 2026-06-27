FROM apache/spark:3.5.1-python3

USER root

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Venv outside /app so bind mounts don't clobber it
ENV UV_PROJECT_ENVIRONMENT=/venv
ENV PATH="/venv/bin:${PATH}"
ENV UV_PYTHON_INSTALL_DIR=/opt/uv_python

WORKDIR /app

# Copy lockfile too for reproducible installs
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --python 3.10

COPY . .

# Drop root
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app /venv /opt/uv_python
USER appuser

EXPOSE 8000