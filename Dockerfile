FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir .
ENV APP_ENV=production APP_MODE=cli
EXPOSE 8080
CMD ["sh", "-c", "if [ \"$APP_MODE\" = \"server\" ]; then python scripts/io_server.py; else python main.py; fi"]
