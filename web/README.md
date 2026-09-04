# Infrangible Web Dashboard (React / Next.js)

Dashboard analítico y de auditoría para el Sistema Autónomo de Trading de Opciones y Acciones en Alpaca Paper Trading.

Diseñado para desplegarse **automáticamente en Vercel con cero configuración**.

---

## 🚀 Despliegue Automático en Vercel

### Configuración en Vercel
1. Inicia sesión en [Vercel](https://vercel.com).
2. Haz clic en **"Add New Project"** e importa este repositorio de GitHub.
3. En la pantalla de configuración de importación (o en **Project Settings -> General**):
   - **Root Directory**: Haz clic en **Edit** y selecciona la carpeta `web`.
   - Vercel reconocerá automáticamente el framework como **Next.js**.
4. En **Build & Development Settings**:
   - Mantén los valores predeterminados (todos los toggles apagados: Build Command `next build`, Output Directory `.next`, Install Command `npm install`).
5. Haz clic en **"Deploy"**. En ~1 minuto la web estará pública y lista.

### Variables de Entorno Opcionales en Vercel
La aplicación web funciona **out-of-the-box** mostrando los datos históricos y auditorías del agente. Si deseas que se conecte directamente a tu cuenta de Alpaca Paper Trading en tiempo real, agrega en **Project Settings -> Environment Variables**:
- `APCA_API_KEY_ID`: Tu clave API de Alpaca Paper Trading
- `APCA_API_SECRET_KEY`: Tu clave secreta de Alpaca Paper Trading
- `APCA_API_BASE_URL`: `https://paper-api.alpaca.markets` (por defecto)

---

## 💻 Ejecución Local

Para correr el dashboard en tu máquina local:

```bash
cd web
npm install
npm run dev
```

Abre [http://localhost:3000](http://localhost:3000) en tu navegador.

---

## 📊 Características del Dashboard

1. **Identificación de Activos Operados**:
   - Visualización clara del Ticker (AAPL, SPY, QQQ, NVDA, TSLA).
   - Distinción entre acciones (**Equity**) y opciones (**CALL/PUT** con Strike y días a vencimiento DTE).
   - Cantidad, acción (**BUY/SELL**) y coste total de cada posición.

2. **Resultado ("si fueron buenos o no")**:
   - Etiqueta de desenlace: **APROBADO & EJECUTADO (FILLED)** en verde, **BLOQUEADO POR RIESGO (REJECTED)** en rojo/ámbar, o **SIMULADO**.
   - Precio de llenado en mercado y protección inmediata del capital.

3. **Razonamiento del Agente & Veredicto de Riesgo**:
   - **Razonamiento de la IA**: Muestra la estrategia cuantitativa, tipo de señal (e.g. `BULLISH_CALL_MOMENTUM`, `QUICK_TRADE`) y explicación técnica textual.
   - **Veredicto del Risk Engine**: Explicación detallada de la regla de protección activada (e.g., Spread Bid/Ask excesivo > 5.0%, horizonte 0-DTE pin risk, o límite de presupuesto del 5%).

4. **Endpoints ya Disponibles**:
   - Pestaña interactiva con los endpoints de Alpaca (`GET /v2/account`, `GET /v2/orders`, `GET /v2/positions`, `GET /v2/clock`) y las rutas del agente (`GET /api/trades`, `GET /api/stats`).
   - Inspector de respuestas JSON con 1 clic.

---

## 🔒 Preservación del Código Funcional
Todo el código del dashboard reside en `web/` y la configuración de despliegue en `vercel.json`. Ningún archivo funcional de Python en `src/`, `tests/` o `scripts/` ha sido modificado.

