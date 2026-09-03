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
# La suite verifica (F1.5-01) que el packaging del repo incluya el Dockerfile
# que compila el CLI oficial de Alpaca (tier 2 de R1) — se empaqueta también
# aquí para que ese check de integridad siga siendo válido dentro de la imagen.
COPY .devcontainer/ ./.devcontainer/

# Gate de build: la suite debe pasar al 100% (R4) antes de que la imagen sea usable.
# No requiere credenciales de Alpaca — corre 100% offline sobre MockMCPTransport.
RUN python -m pytest tests/ -q

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

VOLUME ["/app/logs"]

ENTRYPOINT ["python", "src/main.py"]
CMD ["--mode", "loop", "--interval", "300"]
