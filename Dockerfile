ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
WORKDIR /app
ARG SKIP_REQUIREMENTS_INSTALL=false
COPY requirements.txt pyproject.toml ./
RUN if [ "$SKIP_REQUIREMENTS_INSTALL" != "true" ]; then pip install --no-cache-dir -r requirements.txt; fi
COPY . .
RUN pip install --no-cache-dir --no-build-isolation --no-deps .
ENV APP_ENV=production APP_MODE=cli
EXPOSE 8080
CMD ["sh", "-c", "if [ \"$APP_MODE\" = \"server\" ]; then python scripts/io_server.py; else python main.py; fi"]
