# AI Opportunity Radar — backend (FastAPI + scheduler)
# Build:  docker build -t opportunity-radar .
# Run:    docker run --env-file .env -p 8000:8000 opportunity-radar
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so code changes don't bust the layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# start.py runs the API and the APScheduler loops in one process,
# so a single container is the whole control plane.
CMD ["python", "start.py"]
