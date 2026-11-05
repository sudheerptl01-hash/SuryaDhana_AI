FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/master-controller/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy scripts and shared modules
COPY scripts/ /app/scripts/
COPY shared/ /app/shared/

ENV PYTHONPATH=/app
ENV PYTHON_BIN=python

EXPOSE 8008

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8008/health || exit 1

CMD ["python", "scripts/master_controller.py"]
