# syntax=docker/dockerfile:1
#
# Imagen de despliegue para el Alpaca AI Options Trading Agent.
# Incluye `uv`/`uvx` porque StdioMCPTransport lanza el servidor MCP oficial
# de Alpaca con `uvx alpaca-mcp-server` en tiempo de ejecución (R1). El
# servidor oficial (alpacahq/alpaca-mcp-server) es un paquete Python en
# PyPI, no un paquete npm — no se necesita Node.js/npx para nada aquí.
#
# Build multi-stage: el stage `test` corre la suite completa como gate
# (necesita ver tests/ y .devcontainer/, que test_f1_5_01 verifica como
# parte del packaging del repo), pero NINGUNO de esos archivos de
# desarrollo/test termina en la imagen final `runtime` — solo se copia
# un marcador que prueba que el gate se ejecutó y pasó.

FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt uv

COPY src/ ./src/

# ---- stage de test: gate de build (R4), no se incluye en la imagen final ----
FROM base AS test
COPY tests/ ./tests/
COPY .devcontainer/ ./.devcontainer/
# No requiere credenciales de Alpaca — corre 100% offline sobre MockMCPTransport.
RUN python -m pytest tests/ -q && touch /tests-passed

# ---- stage final de runtime: solo código de producción ----
FROM base AS runtime
COPY --from=test /tests-passed /tests-passed

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

VOLUME ["/app/logs"]

ENTRYPOINT ["python", "src/main.py"]
CMD ["--mode", "loop", "--interval", "300"]
