FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY requirements-production.txt requirements-windows-tested.txt pyproject.toml README.md SECURITY.md alembic.ini ./
RUN pip install --no-cache-dir setuptools wheel \
    && pip install --no-cache-dir -r requirements-production.txt \
    && pip install --no-cache-dir --no-deps --no-build-isolation -e .

COPY src ./src
COPY data ./data
COPY artifacts ./artifacts
COPY docs ./docs
COPY migrations ./migrations
COPY workspace ./workspace
COPY scripts ./scripts
RUN chmod +x scripts/render_start.sh

RUN python scripts/production_preflight.py --static

EXPOSE 8000
CMD ["uvicorn", "mdt.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
