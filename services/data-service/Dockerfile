FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared/ /app/shared/
COPY services/data-service/ /app/services/data-service/
# The ML dataset job (ml_dataset.py) reuses the one feature/label implementation.
COPY services/feature-service/feature_engine.py /app/services/feature-service/feature_engine.py

WORKDIR /app/services/data-service

ENV PYTHONPATH=/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--timeout-keep-alive", "75"]
