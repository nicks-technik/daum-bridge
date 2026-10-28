FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libffi-dev \
    libssl-dev \
    libbluetooth-dev \
    libdbus-1-dev \
    libglib2.0-dev \
    bluez \
    bluetooth \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app
COPY . /app

RUN uv sync --no-dev

EXPOSE 8080

ENV DAUM_CONFIG=/app/config.yaml

CMD ["uv", "run", "daum-bridge", "run", "--config", "/app/config.yaml"]
