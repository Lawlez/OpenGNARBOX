# ─────────────────────────────────────────────────────────────────────
# OpenGNARBOX Core —- Multi-stage Docker build
#
# Target: x86_64 (Intel Atom E3940, GNARBOX 2.0 SoC)
# Integrates into the existing Docker Swarm
# ─────────────────────────────────────────────────────────────────────

# Stage 1: Build Frontend (Vite)
FROM node:20-alpine AS frontend-builder
WORKDIR /app/importool
# Copy only package.json
COPY importool/package.json ./
RUN npm install --no-audit --no-fund
COPY importool/ ./
RUN npm run build

# Stage 2: Backend (FastAPI)
FROM python:3.11-alpine
WORKDIR /app

# Install system deps for aiofiles and potential native extensions
RUN apk add --no-cache gcc musl-dev

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apk del gcc musl-dev

# Copy Backend Source
COPY backend/ ./

# Copy Frontend Build to backend's frontend/dist
COPY --from=frontend-builder /app/importool/dist ./frontend/dist

# Labels for the GNARBOX Docker Swarm (traefik routing)
LABEL traefik.enable="true"
LABEL traefik.http.routers.opengnar.rule="PathPrefix(\`/opengnar\`)"
LABEL traefik.http.routers.opengnar.middlewares="opengnar"
LABEL traefik.http.middlewares.opengnar.stripprefix.prefixes="/opengnar"
LABEL traefik.http.services.opengnar.loadbalancer.server.port="8000"

# Expose port and start FastAPI
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
