# Read-only osTicket MCP over Streamable HTTP.
# Credentials and the auth token come from the environment at run time, never from the image.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
FROM ${PYTHON_IMAGE} AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements-build.lock ./
RUN pip install --require-hashes -r requirements-build.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --no-deps --no-build-isolation --wheel-dir /wheels .

FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
COPY --from=builder /wheels /wheels
RUN pip install --no-deps /wheels/*.whl \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin mcp

USER mcp
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["mcp-mysql"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
