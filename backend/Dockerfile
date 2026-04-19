FROM python:3.11-slim

WORKDIR /app

# System deps: curl for healthcheck, build tools for compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source
# (layer cached unless pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

COPY . .

RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
