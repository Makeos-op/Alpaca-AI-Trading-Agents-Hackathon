# syntax=docker/dockerfile:1
#
# Imagen de despliegue para el Alpaca AI Options Trading Agent.
# Incluye Node.js/npx porque StdioMCPTransport lanza
# `npx -y @alpacahq/mcp-server-alpaca` en tiempo de ejecución (R1).

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY tests/ ./tests/

# Gate de build: la suite debe pasar al 100% (R4) antes de que la imagen sea usable.
# No requiere credenciales de Alpaca — corre 100% offline sobre MockMCPTransport.
RUN python -m pytest tests/ -q

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

VOLUME ["/app/logs"]

ENTRYPOINT ["python", "src/main.py"]
CMD ["--mode", "loop", "--interval", "300"]
