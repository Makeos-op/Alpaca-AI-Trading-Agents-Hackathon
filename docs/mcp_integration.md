# Alpaca MCP & CLI Gateway Integration / Integración de Gateway Alpaca MCP y CLI

[English](#english) | [Español](#español)

---

<a name="english"></a>
## English Documentation

### Overview
The `AlpacaGateway` class (`src/execution/mcp_gateway.py`) fulfills Hackathon Requirements R1 and R2 by providing unified, protocol-compliant access to Alpaca Paper Trading via the official Model Context Protocol (MCP) server (`@alpacahq/mcp-server-alpaca` / `alpaca-mcp-server`) or the official Alpaca CLI (`/usr/bin/alpaca`).

### 1. Transport Hierarchy & Fallback Ladder
The gateway implements an intelligent multi-tier transport architecture via `BaseAlpacaTransport`:

```
               [ AlpacaGateway(mode="auto") ]
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
   [ StdioMCPTransport ]  [ CLITransport ]  [ MockMCPTransport ]
   (Primary Protocol)    (Local CLI Backup) (Offline Simulation)
```

- **Resilient Fallback Ladder**: When `mode="auto"`, the gateway initiates `StdioMCPTransport`. If stdio communication fails or binary is unavailable, it automatically transitions to `CLITransport` (including automated non-interactive profile configuration). If CLI execution is unavailable, it falls back to `MockMCPTransport` for offline testing.

### 2. ALPACA_TOOLSETS and the "assets" Toolset (R1 Fix)
In `alpaca-mcp-server` v2.3.1, tools are modularly registered according to the `ALPACA_TOOLSETS` environment variable.
- **Root Cause of Prior Failure**: Previous configurations used `"account,trading,options-data,stock-data"`, omitting `"assets"`. In FastMCP OpenAPI generation, the `LegacyClock` (`get_clock`), `LegacyCalendar` (`get_calendar`), and `get-options-contracts` tools are defined exclusively within the `"assets"` toolset. Missing `"assets"` resulted in `-32601: Unknown tool: 'get_clock'` errors and triggered unexpected fallback to mock mode.
- **Resolution**: `StdioMCPTransport._build_env()` sets the default to:
  ```
  ALPACA_TOOLSETS="account,trading,assets,options-data,stock-data"
  ```
  This ensures `get_clock`, `get_calendar`, and `get_option_contracts` are registered and discoverable. User-defined environment overrides via `ALPACA_TOOLSETS` are also respected.

### 3. Stdio Process Robustness & Binary Auto-Discovery
`StdioMCPTransport` incorporates several production-grade safeguards:
1. **Intelligent Binary Resolution**:
   The gateway searches for MCP server binaries in the following order:
   - Explicit `ALPACA_MCP_COMMAND` environment override
   - `uvx alpaca-mcp-server` (if `uvx` is in `PATH`)
   - `alpaca-mcp-server` executable (in `PATH` or `/usr/local/bin/alpaca-mcp-server`)
   - `sys.executable -m alpaca_mcp_server`
   - `npx -y @alpacahq/mcp-server-alpaca`
2. **Background Stderr Drain Daemon Thread**:
   To prevent operating system pipe buffer deadlocks (POSIX 64KB pipe buffer limit) caused by verbose FastMCP debug logs, `StdioMCPTransport._spawn_process()` launches a dedicated daemon thread running `_drain_stderr()` that continuously empties `proc.stderr` without blocking execution.
3. **15-Second Handshake Timeout**:
   Default timeout is configured to 15.0 seconds (`timeout_seconds=15.0`) to comfortably accommodate OpenAPI route generation during cold starts.

### 4. Alpaca CLI Transport Automation (CLITransport)
`CLITransport` manages execution of `/usr/bin/alpaca` (Go binary v0.0.13):
1. **Profile Authentication Verification (`is_authenticated`)**:
   Executes `/usr/bin/alpaca account get` (or fallback `alpaca clock`), returning `True` if credentials and active session exist, and `False` otherwise.
2. **Non-Interactive Auto-Configuration (`auto_configure_profile`)**:
   If the CLI is unauthenticated but `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` are present in the environment, it automatically executes:
   ```bash
   alpaca profile login --api-key
   ```
   piping `<APCA_API_KEY_ID>\n<APCA_API_SECRET_KEY>\n` directly into `stdin`. This configures the profile without human interaction.
3. **Direct Parameter Calling**:
   Executes subcommands directly without injecting unsupported `--format json` flags, extracting structured JSON responses even if preceded by diagnostic output.

### 5. Multi-Asset Order Routing
`StdioMCPTransport.submit_order()` and `AlpacaGateway.submit_order()` evaluate target symbols using the standard OCC regular expression (`is_occ_symbol`):
- **OCC Option Symbols** (e.g. `SPY260930C00500000`): Dispatched to `place_option_order` in MCP or `submit_option_order` in Gateway.
- **Stock / ETF Tickers** (e.g. `SPY`, `AAPL`): Dispatched to `place_stock_order` in MCP or `submit_stock_order` in Gateway.

---

<a name="español"></a>
## Documentación en Español

### Descripción General
La clase `AlpacaGateway` (`src/execution/mcp_gateway.py`) cumple los Requisitos R1 y R2 del Hackathon al brindar acceso unificado y conforme al protocolo a Alpaca Paper Trading a través del servidor oficial Model Context Protocol (MCP) (`@alpacahq/mcp-server-alpaca` / `alpaca-mcp-server`) o el CLI oficial de Alpaca (`/usr/bin/alpaca`).

### 1. Jerarquía de Transportes y Cascada de Fallback
El gateway implementa una arquitectura multicapa mediante `BaseAlpacaTransport`:

```
               [ AlpacaGateway(mode="auto") ]
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
   [ StdioMCPTransport ]  [ CLITransport ]  [ MockMCPTransport ]
   (Protocolo Principal) (Respaldo CLI)    (Simulación Offline)
```

- **Cascada de Fallback Resiliente**: En `mode="auto"`, el gateway inicia `StdioMCPTransport`. Si la comunicación stdio falla o el binario no está disponible, realiza transición automática a `CLITransport` (incluyendo auto-configuración no interactiva del perfil). Si el CLI tampoco está disponible, activa `MockMCPTransport` para pruebas offline.

### 2. Configuración de ALPACA_TOOLSETS y Toolset "assets" (Corrección R1)
En `alpaca-mcp-server` v2.3.1, las herramientas se registran modularmente según la variable de entorno `ALPACA_TOOLSETS`.
- **Causa Raíz del Error Anterior**: Configuraciones previas usaban `"account,trading,options-data,stock-data"`, omitiendo `"assets"`. Durante la generación de rutas FastMCP OpenAPI, las herramientas `LegacyClock` (`get_clock`), `LegacyCalendar` (`get_calendar`) y `get-options-contracts` están definidas exclusivamente bajo el toolset `"assets"`. La ausencia de `"assets"` provocaba el error `-32601: Unknown tool: 'get_clock'`, forzando fallback indebido al mock.
- **Solución Implementada**: `StdioMCPTransport._build_env()` define por defecto:
  ```
  ALPACA_TOOLSETS="account,trading,assets,options-data,stock-data"
  ```
  Esto garantiza el registro y descubrimiento de `get_clock`, `get_calendar` y `get_option_contracts`. Se respeta cualquier configuración personalizada definida por el usuario.

### 3. Robustez de Proceso Stdio y Auto-Descubrimiento de Binarios
`StdioMCPTransport` incluye mecanismos de nivel productivo:
1. **Resolución Inteligente de Binarios**:
   Busca ejecutables en el siguiente orden:
   - Override explícito en variable `ALPACA_MCP_COMMAND`
   - `uvx alpaca-mcp-server` (si `uvx` está en el `PATH`)
   - Binario `alpaca-mcp-server` (en `PATH` o `/usr/local/bin/alpaca-mcp-server`)
   - `sys.executable -m alpaca_mcp_server`
   - `npx -y @alpacahq/mcp-server-alpaca`
2. **Hilo Demonio para Drenaje Continuo de Stderr**:
   Para evitar bloqueos por saturación del buffer de tuberías del sistema operativo (límite POSIX de 64KB) ante logs detallados de FastMCP, `_spawn_process()` ejecuta un hilo demonio `_drain_stderr()` que vacía `proc.stderr` continuamente sin interferir con la ejecución principal.
3. **Timeout de Handshake de 15 Segundos**:
   Se establece un tiempo límite de 15.0 segundos (`timeout_seconds=15.0`) para tolerar el arranque en frío del servidor MCP.

### 4. Automatización del Transporte Alpaca CLI (CLITransport)
`CLITransport` gestiona la invocación de `/usr/bin/alpaca` (binario compilado en Go v0.0.13):
1. **Verificación de Autenticación (`is_authenticated`)**:
   Ejecuta `/usr/bin/alpaca account get` (o fallback a `alpaca clock`), retornando `True` si existe una sesión activa y `False` en caso de error.
2. **Auto-Configuración No Interactiva (`auto_configure_profile`)**:
   Si el CLI no está autenticado pero `APCA_API_KEY_ID` y `APCA_API_SECRET_KEY` están definidas en el entorno, ejecuta automáticamente:
   ```bash
   alpaca profile login --api-key
   ```
   canalizando `<APCA_API_KEY_ID>\n<APCA_API_SECRET_KEY>\n` hacia `stdin`, configurando el perfil sin requerir intervención del operador.
3. **Invocación Directa de Comandos**:
   Ejecuta subcomandos directamente sin inyectar flags no soportados como `--format json`, extrayendo la carga útil JSON estructurada aun en presencia de logs diagnósticos.

### 5. Enrutamiento Multi-Activo de Órdenes
`StdioMCPTransport.submit_order()` y `AlpacaGateway.submit_order()` discriminan el tipo de activo mediante la expresión regular estándar OCC (`is_occ_symbol`):
- **Símbolos OCC de Opciones** (ej. `SPY260930C00500000`): Enrutados a `place_option_order` en MCP o `submit_option_order` en Gateway.
- **Acciones y ETFs** (ej. `SPY`, `AAPL`): Enrutados a `place_stock_order` en MCP o `submit_stock_order` en Gateway.
