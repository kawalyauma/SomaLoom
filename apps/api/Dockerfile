FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api:/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr clamav fonts-dejavu-core libcairo2-dev pkg-config gcc python3-dev && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --upgrade "pip>=26.2" && pip install --no-cache-dir -r requirements.lock
COPY apps/api apps/api
COPY contracts contracts
COPY services services
# Publishing formats require vector PDF and editable Office document libraries.
RUN pip install --no-cache-dir -r services/export/requirements.txt -r services/extraction/requirements.txt -r services/ingestion/requirements.txt
COPY db db
COPY alembic.ini ./
COPY tools tools
RUN mkdir -p /data/resources && chown -R app:app /data /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
