FROM python:3.10-slim

# Install OpenJDK 17 (required for PySpark) and basic build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends openjdk-17-jre-headless procps gcc curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install uv from official Astral binary container
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Tell uv to install directly into the system python environment
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

COPY pyproject.toml ./
RUN uv pip install -r pyproject.toml

COPY . .
