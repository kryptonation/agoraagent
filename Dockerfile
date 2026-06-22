# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Build Python Backend
FROM python:3.13-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy python dependencies definitions
COPY pyproject.toml uv.lock ./
# Install project dependencies
RUN uv pip install --system -r pyproject.toml

# Copy backend source code
COPY src/ /app/src/

# Copy compiled React frontend assets from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Expose server port
EXPOSE 8000

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PORT=8000

# Start server
CMD ["uv", "run", "--package", "morekick", "python", "-m", "uvicorn", "morekick.server:app", "--host", "0.0.0.0", "--port", "8000"]
