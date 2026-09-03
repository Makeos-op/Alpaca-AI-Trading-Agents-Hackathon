# Original User Request

## 2026-09-03T13:38:59Z

# Teamwork Project Prompt

> Requested team: Full team

Implementación de integración oficial con Alpaca MCP (`@alpacahq/mcp-server-alpaca`) y/o Alpaca CLI en el sistema de trading autónomo de opciones, incorporando un guardarraíl determinista de Risk Engine (regla del 5%) que filtre las decisiones de los agentes de IA para blindar la operativa contra alucinaciones.

Working directory: `/workspaces/Alpaca-AI-Trading-Agents-Hackathon`
Integrity mode: demo

## Requirements

### R1. Conexión Real al Servidor MCP Oficial de Alpaca vía Stdio
Integrar el cliente oficial de MCP en Python (`mcp`) para comunicarse mediante protocolo stdio con `@alpacahq/mcp-server-alpaca` (lanzado con `npx`) o el CLI oficial de Alpaca. Reemplazar las llamadas directas ad-hoc para que las consultas de balance de cuenta, reloj de mercado, y herramientas de trading cumplan formalmente con las especificaciones del Hackathon ("MCP or CLI").

### R2. Guardarraíl Determinista Anti-Alucinación (Risk Engine & Limits)
Asegurar que toda propuesta de trading generada por el agente de estrategia pase obligatoriamente por el motor determinista de riesgo (`RiskEngine`) antes de cualquier ejecución. El motor debe validar de forma estricta:
- Regla del 5%: Ninguna posición puede arriesgar más del 5% del valor de la cartera / buying power efectivo.
- Spread bid-ask y umbrales de liquidez mínimos en la cadena de opciones.
- Validación de delta, theta y fecha de expiración (DTE).
- Si el Risk Engine emite un veredicto de rechazo, la orden queda bloqueada y no se realiza ninguna llamada de ejecución al broker.

### R3. Pipeline de Ejecución Segura y Logging Estructurado
Permitir la ejecución de órdenes aprobadas a través de la herramienta de trading MCP o CLI oficial de Alpaca en entorno Paper Trading, manteniendo soporte para `--mode dry-run`. Registrar de forma auditable en `logs/trades.jsonl` todo el ciclo: datos de mercado consultados vía MCP, propuesta del agente, dictamen detallado del Risk Engine, y resultado de la orden.

### R4. Suite de Verificación Automatizada
Desarrollar y ejecutar tests unitarios e integrados que verifiquen objetivamente:
- Comunicación y parsing del protocolo MCP stdio con Alpaca.
- Bloqueo efectivo de trades alucinados o fuera de rango por parte del Risk Engine.
- Correcta ejecución y logging de trades que sí cumplen con todos los criterios de riesgo.

## Acceptance Criteria

### Protocolo MCP / CLI
- [ ] El sistema se comunica con el servidor MCP oficial de Alpaca (`@alpacahq/mcp-server-alpaca`) mediante transporte stdio en Python o mediante comandos del CLI oficial de Alpaca.
- [ ] No existen llamadas de ejecución de órdenes que eludan el protocolo MCP/CLI o el motor de riesgo.

### Robustez y Control de Alucinaciones
- [ ] Cualquier propuesta de trade generada por la IA que viole la regla del 5% o los límites de salud de cuenta es rechazada con un veredicto explícito y registrada en log, sin enviar la orden al broker.
- [ ] El pipeline completo se ejecuta sin errores tanto en modo `--mode dry-run` como en `--mode scan` contra el entorno Paper Trading.

### Verificación y Calidad
- [ ] La suite de pruebas automatizadas pasa al 100%, validando los escenarios de aprobación, rechazo por riesgo y comunicación con las herramientas MCP.
- [ ] La documentación del repositorio refleja con precisión la arquitectura de integración MCP + Risk Engine Guardrail.

## 2026-09-03T19:19:02Z

# Teamwork Project Prompt

> Requested team: Full team

Resolución del error de toolset en Alpaca MCP (`get_clock` en `assets`), automatización de autenticación para Alpaca CLI, e implementación de modo Scalping / Fast-Trade que permita verificar trades automáticos visibles en tiempo real en la web de Alpaca Paper Trading.

Working directory: `/workspaces/Alpaca-AI-Trading-Agents-Hackathon`
Integrity mode: demo

## Requirements

### R1. Corrección del Toolset de Alpaca MCP y Estabilidad Stdio
- Configurar `ALPACA_TOOLSETS` en `StdioMCPTransport` para incluir el set `"assets"` (`"account,trading,assets,options-data,stock-data"`), habilitando las herramientas oficiales `get_clock`, `get_calendar` y `get_option_contracts`.
- Garantizar que el handshake y la comunicación stdio con `uvx alpaca-mcp-server` o `alpaca-mcp-server` ejecute sin fallback inesperado a mock en entornos productivos con credenciales válidas.

### R2. Integración y Automatización de Autenticación Alpaca CLI
- Proveer soporte en `CLITransport` para detectar perfiles autenticados o ejecutar auto-configuración no interactiva usando las variables de entorno `APCA_API_KEY_ID` y `APCA_API_SECRET_KEY` vía `alpaca profile login --api-key`.
- Documentar y validar el flujo de login manual y desatendido para el usuario en consola.

### R3. Estrategia de Scalping y Modo Fast-Trade para Validación Web Inmediata
- Desarrollar un modo `--mode scalp` (o flag `--quick-trade`) que opere con temporalidades rápidas (1Min/5Min) o ejecute una orden de test determinista validada por el `RiskEngine` (regla del 5%).
- Permitir tanto órdenes de opciones líquidas como órdenes de acciones/ETFs (ej. SPY, AAPL) para garantizar que el usuario pueda ver el trade ejecutado en tiempo real en el dashboard web de Alpaca Paper Trading (`https://app.alpaca.markets`), incluso si el mercado de opciones presenta limitaciones horarias.
- Registrar el ciclo completo en `logs/trades.jsonl` con formato auditable Draft-07.

### R4. Suite de Pruebas y Demostración de Ejecución Automática
- Actualizar y ejecutar la suite de tests unitarios e integrados (E2E) para cubrir el nuevo toolset de MCP, los comandos de CLI y el flujo de ejecución automática en Paper Trading.

## Acceptance Criteria

### Compatibilidad MCP & CLI
- [ ] La llamada `gw.get_clock()` sobre `StdioMCPTransport` resuelve exitosamente contra el servidor MCP oficial sin error de `Unknown tool: 'get_clock'`.
- [ ] `CLITransport` puede autenticar y ejecutar consultas de cuenta y órdenes vía `/usr/bin/alpaca`.

### Ejecución Visible en Alpaca Web
- [ ] Ejecutar `python src/main.py --mode scalp` o `--quick-trade` genera y transmite una orden real al entorno Paper Trading de Alpaca, reflejándose con su Order ID en el dashboard web.
- [ ] Todo trade pasa obligatoriamente por el filtro de riesgo del `RiskEngine` antes de emitirse.

### Cobertura y Estabilidad
- [ ] 100% de los tests unitarios y de integración continúan pasando.
- [ ] Documentación actualizada en español e inglés en `docs/` y `README.md`.

