"use client";

import React, { useState, useMemo, useEffect } from "react";
import {
  Activity,
  ShieldCheck,
  ShieldAlert,
  TrendingUp,
  DollarSign,
  Layers,
  Search,
  Filter,
  Code2,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Info,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Briefcase,
  Eye,
  RefreshCw,
} from "lucide-react";
import {
  TradeRecord,
  AccountInfo,
  ApiEndpointItem,
  ExecutionStatus,
} from "@/types/trade";
import {
  HISTORICAL_TRADES,
  DEFAULT_ACCOUNT_SNAPSHOT,
  AVAILABLE_API_ENDPOINTS,
} from "@/data/historicalTrades";

export default function Dashboard() {
  const [trades, setTrades] = useState<TradeRecord[]>(HISTORICAL_TRADES);
  const [account, setAccount] = useState<AccountInfo>(DEFAULT_ACCOUNT_SNAPSHOT);
  const [dataSource, setDataSource] = useState<string>("live_trades_jsonl");
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [selectedTicker, setSelectedTicker] = useState<string>("ALL");
  const [selectedStatus, setSelectedStatus] = useState<string>("ALL");
  const [selectedAssetClass, setSelectedAssetClass] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"trades" | "endpoints" | "risk">("trades");
  const [inspectedTrade, setInspectedTrade] = useState<TradeRecord | null>(null);
  const [activeEndpointModal, setActiveEndpointModal] = useState<ApiEndpointItem | null>(null);

  // Sincronización en vivo con /api/trades (que lee logs/trades.jsonl) y /api/account
  const fetchLiveTrades = async () => {
    setIsRefreshing(true);
    try {
      const res = await fetch("/api/trades");
      if (res.ok) {
        const data = await res.json();
        if (data.trades && Array.isArray(data.trades) && data.trades.length > 0) {
          setTrades(data.trades);
          setDataSource(data.source);
        }
      }
      const accRes = await fetch("/api/account");
      if (accRes.ok) {
        const accData = await accRes.json();
        if (accData.account) {
          setAccount(accData.account);
        }
      }
    } catch (e) {
      console.error("Error al sincronizar con /api/trades:", e);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchLiveTrades();
    const interval = setInterval(fetchLiveTrades, 6000);
    return () => clearInterval(interval);
  }, []);

  // Filtros dinámicos
  const filteredTrades = useMemo(() => {
    return trades.filter((t) => {
      const matchTicker =
        selectedTicker === "ALL" || t.ticker.toUpperCase() === selectedTicker.toUpperCase();
      const matchStatus =
        selectedStatus === "ALL" || t.execution_status === selectedStatus;
      const matchAsset =
        selectedAssetClass === "ALL" || t.asset_class === selectedAssetClass;
      const q = searchQuery.toLowerCase().trim();
      const matchQuery =
        !q ||
        t.ticker.toLowerCase().includes(q) ||
        t.strategy_name.toLowerCase().includes(q) ||
        t.agent_proposal.rationale.toLowerCase().includes(q) ||
        t.option_symbol.toLowerCase().includes(q);

      return matchTicker && matchStatus && matchAsset && matchQuery;
    });
  }, [trades, selectedTicker, selectedStatus, selectedAssetClass, searchQuery]);

  // KPIs
  const stats = useMemo(() => {
    const total = trades.length;
    const executed = trades.filter((t) => t.execution_status === "FILLED").length;
    const rejected = trades.filter((t) => t.execution_status === "REJECTED" || t.execution_status === "ERROR").length;
    const errors = trades.filter((t) => t.execution_status === "ERROR").length;
    const approvalRate = total > 0 ? (executed / total) * 100 : 0;
    const committedCost = trades
      .filter((t) => t.execution_status === "FILLED")
      .reduce((acc, t) => acc + parseFloat(t.trade_cost || "0"), 0);

    const uniqueTickers = Array.from(new Set(trades.map((t) => t.ticker)));

    return {
      total,
      executed,
      rejected,
      errors,
      approvalRate: approvalRate.toFixed(1),
      committedCost: committedCost.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
      }),
      uniqueTickers,
    };
  }, [trades]);

  const uniqueTickerList = useMemo(() => {
    return ["ALL", ...Array.from(new Set(trades.map((t) => t.ticker)))];
  }, [trades]);

  return (
    <div className="min-h-screen bg-[#0b0f19] text-slate-100 p-4 md:p-8">
      {/* Header Superior */}
      <header className="max-w-7xl mx-auto mb-8 flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-6">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="flex h-3 w-3 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
            </span>
            <span className="text-xs uppercase tracking-widest text-emerald-400 font-semibold bg-emerald-950/60 border border-emerald-800/50 px-2.5 py-0.5 rounded-full">
              Alpaca Paper Trading Live
            </span>
            <span className="text-xs text-indigo-400 border border-indigo-800/50 bg-indigo-950/60 px-2 py-0.5 rounded-full flex items-center gap-1 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400"></span>
              {dataSource === "live_trades_jsonl" ? "Sincronizado con logs/trades.jsonl" : "Snapshot Verificado"}
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white flex items-center gap-2">
            Infrangible AI Trading Dashboard
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Auditoría de órdenes, razonamiento cuantitativo del agente autónomo y protección del Risk Engine (5% max risk).
          </p>
        </div>

        {/* Info de Cuenta Alpaca Paper & Botón de Refresco */}
        <div className="flex items-center gap-3">
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 flex items-center gap-4 text-xs">
            <div>
              <div className="text-slate-400 uppercase tracking-wider text-[10px]">Portafolio</div>
              <div className="text-base font-bold text-white mt-0.5">
                ${parseFloat(account.portfolio_value).toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </div>
            </div>
            <div className="h-8 w-px bg-slate-800"></div>
            <div>
              <div className="text-slate-400 uppercase tracking-wider text-[10px]">Buying Power</div>
              <div className="text-base font-bold text-emerald-400 mt-0.5">
                ${parseFloat(account.buying_power).toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </div>
            </div>
            <div className="h-8 w-px bg-slate-800"></div>
            <div>
              <div className="text-slate-400 uppercase tracking-wider text-[10px]">Cash</div>
              <div className="text-base font-bold text-slate-200 mt-0.5">
                ${parseFloat(account.cash).toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </div>
            </div>
          </div>

          <button
            onClick={fetchLiveTrades}
            title="Sincronizar con logs/trades.jsonl"
            className="p-3 bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 rounded-xl text-slate-300 hover:text-white transition flex items-center justify-center"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin text-indigo-400" : ""}`} />
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto space-y-6">
        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">Total Evaluados</span>
              <Activity className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="text-2xl font-bold text-white">{stats.total}</div>
            <div className="text-xs text-slate-400 mt-1 flex items-center gap-1">
              <span className="text-indigo-400 font-medium">{stats.uniqueTickers.length}</span> activos en bitácora
            </div>
          </div>

          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">Trades Aprobados</span>
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="text-2xl font-bold text-emerald-400">{stats.executed}</div>
            <div className="text-xs text-slate-400 mt-1">
              Tasa de Aprobación: <span className="text-emerald-400 font-semibold">{stats.approvalRate}%</span>
            </div>
          </div>

          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">Bloqueos / Fallos</span>
              <ShieldAlert className="h-4 w-4 text-rose-400" />
            </div>
            <div className="text-2xl font-bold text-rose-400">{stats.rejected}</div>
            <div className="text-xs text-slate-400 mt-1">
              {stats.errors > 0 ? (
                <span className="text-amber-400 font-medium">{stats.errors} errores de broker auditados</span>
              ) : (
                "Protegidos por guardrails de riesgo"
              )}
            </div>
          </div>

          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">Capital Ejecutado</span>
              <DollarSign className="h-4 w-4 text-cyan-400" />
            </div>
            <div className="text-2xl font-bold text-cyan-300">{stats.committedCost}</div>
            <div className="text-xs text-slate-400 mt-1">Límite por trade: 5% máx</div>
          </div>
        </div>

        {/* Selector de Vistas / Pestañas */}
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveTab("trades")}
              className={`px-4 py-2 rounded-lg text-xs font-medium transition flex items-center gap-2 ${
                activeTab === "trades"
                  ? "bg-indigo-600/20 text-indigo-300 border border-indigo-500/40"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
              }`}
            >
              <Briefcase className="h-3.5 w-3.5" />
              Operaciones & Razonamiento ({filteredTrades.length})
            </button>
            <button
              onClick={() => setActiveTab("endpoints")}
              className={`px-4 py-2 rounded-lg text-xs font-medium transition flex items-center gap-2 ${
                activeTab === "endpoints"
                  ? "bg-indigo-600/20 text-indigo-300 border border-indigo-500/40"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
              }`}
            >
              <Code2 className="h-3.5 w-3.5" />
              Endpoints Disponibles (Alpaca & Agente)
            </button>
            <button
              onClick={() => setActiveTab("risk")}
              className={`px-4 py-2 rounded-lg text-xs font-medium transition flex items-center gap-2 ${
                activeTab === "risk"
                  ? "bg-indigo-600/20 text-indigo-300 border border-indigo-500/40"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
              }`}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Auditoría de Guardrails de Riesgo
            </button>
          </div>
        </div>

        {/* PESTAÑA 1: OPERACIONES Y RAZONAMIENTO */}
        {activeTab === "trades" && (
          <div className="space-y-4">
            {/* Barra de Filtros */}
            <div className="bg-slate-900/60 border border-slate-800/90 rounded-xl p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2 flex-1 min-w-[200px]">
                <Search className="h-3.5 w-3.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Buscar por ticker, estrategia o razonamiento..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-full"
                />
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {/* Filtro Ticker */}
                <div className="flex items-center gap-1.5">
                  <span className="text-slate-400">Activo:</span>
                  <select
                    value={selectedTicker}
                    onChange={(e) => setSelectedTicker(e.target.value)}
                    className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    {uniqueTickerList.map((tick) => (
                      <option key={tick} value={tick}>
                        {tick === "ALL" ? "Todos los Activos" : tick}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Filtro Estado */}
                <div className="flex items-center gap-1.5">
                  <span className="text-slate-400">Resultado:</span>
                  <select
                    value={selectedStatus}
                    onChange={(e) => setSelectedStatus(e.target.value)}
                    className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="ALL">Todos los Estados</option>
                    <option value="FILLED">Aprobados / Ejecutados</option>
                    <option value="REJECTED">Bloqueados por Riesgo</option>
                    <option value="ERROR">Fallos de Broker / Error</option>
                    <option value="SIMULATED">Simulados</option>
                  </select>
                </div>

                {/* Filtro Clase de Activo */}
                <div className="flex items-center gap-1.5">
                  <span className="text-slate-400">Tipo:</span>
                  <select
                    value={selectedAssetClass}
                    onChange={(e) => setSelectedAssetClass(e.target.value)}
                    className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="ALL">Acciones & Opciones</option>
                    <option value="equity">Solo Acciones (Equity)</option>
                    <option value="option">Solo Opciones (Call/Put)</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Lista de Operaciones */}
            <div className="space-y-3">
              {filteredTrades.length === 0 ? (
                <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-12 text-center text-slate-400 text-sm">
                  No se encontraron operaciones con los filtros seleccionados.
                </div>
              ) : (
                filteredTrades.map((trade) => {
                  const isApproved = trade.is_approved;
                  const isFilled = trade.execution_status === "FILLED";
                  const isError = trade.execution_status === "ERROR";
                  const isSimulated = trade.execution_status === "SIMULATED";

                  return (
                    <div
                      key={trade.id}
                      className={`bg-slate-900/70 border rounded-xl p-4 transition duration-150 ${
                        isFilled
                          ? "border-emerald-900/40 hover:border-emerald-700/60"
                          : isError
                          ? "border-rose-900/60 hover:border-rose-700/70 bg-rose-950/10"
                          : "border-slate-800 hover:border-slate-700"
                      }`}
                    >
                      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-3">
                        {/* Identificación de la Acción / Activo */}
                        <div className="flex items-center gap-3">
                          <span className="text-lg font-black tracking-wider text-white bg-slate-950 px-3 py-1 rounded-lg border border-slate-800">
                            {trade.ticker}
                          </span>
                          <span
                            className={`text-xs px-2.5 py-0.5 rounded-full font-medium border ${
                              trade.contract_type === "EQUITY"
                                ? "bg-cyan-950/60 text-cyan-400 border-cyan-800/40"
                                : trade.contract_type === "CALL"
                                ? "bg-emerald-950/60 text-emerald-400 border-emerald-800/40"
                                : "bg-purple-950/60 text-purple-400 border-purple-800/40"
                            }`}
                          >
                            {trade.contract_type === "EQUITY"
                              ? "ACCIÓN (Equity)"
                              : `OPCIÓN ${trade.contract_type} ($${trade.strike_price} · ${trade.dte} DTE)`}
                          </span>
                          <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                            {trade.action} × {trade.quantity}
                          </span>
                          {trade.option_symbol && trade.option_symbol !== trade.ticker && (
                            <span className="text-[11px] font-mono text-slate-400 bg-slate-950 px-2 py-0.5 rounded border border-slate-800 hidden sm:inline-block">
                              {trade.option_symbol}
                            </span>
                          )}
                        </div>

                        {/* Resultado ("si fueron buenos o no") */}
                        <div className="flex items-center gap-2">
                          <span
                            className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${
                              isFilled
                                ? "bg-emerald-950 text-emerald-400 border-emerald-800"
                                : isError
                                ? "bg-rose-950 text-rose-300 border-rose-800 animate-pulse"
                                : isSimulated
                                ? "bg-blue-950 text-blue-400 border-blue-800"
                                : "bg-amber-950 text-amber-400 border-amber-800"
                            }`}
                          >
                            {isFilled ? (
                              <>
                                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                                APROBADO & EJECUTADO
                              </>
                            ) : isError ? (
                              <>
                                <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
                                FALLO EN BROKER (422 / ERROR)
                              </>
                            ) : isSimulated ? (
                              <>
                                <Clock className="h-3.5 w-3.5 text-blue-400" />
                                SIMULADO (DRY-RUN)
                              </>
                            ) : (
                              <>
                                <XCircle className="h-3.5 w-3.5 text-amber-400" />
                                RECHAZADO POR RIESGO
                              </>
                            )}
                          </span>

                          <div className="text-right pl-2 border-l border-slate-800">
                            <div className="text-xs text-slate-400">Coste Trade</div>
                            <div className="text-xs font-mono font-bold text-slate-200">
                              ${parseFloat(trade.trade_cost).toFixed(2)}
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Caja de Razonamiento del Agente y Veredicto de Riesgo */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 bg-slate-950/60 rounded-lg p-3 border border-slate-800/60 text-xs">
                        {/* Razonamiento del Agente de IA */}
                        <div>
                          <div className="flex items-center gap-1.5 text-indigo-400 font-semibold mb-1">
                            <Sparkles className="h-3.5 w-3.5" />
                            <span>Razonamiento del Agente ({trade.strategy_name})</span>
                            <span className="ml-auto text-[10px] text-slate-400 bg-slate-900 px-1.5 py-0.2 rounded border border-slate-800">
                              Señal: {trade.agent_proposal.signal_type}
                            </span>
                          </div>
                          <p className="text-slate-300 leading-relaxed">
                            {trade.agent_proposal.rationale}
                          </p>
                        </div>

                        {/* Veredicto y Protección del Motor de Riesgo */}
                        <div>
                          <div className="flex items-center gap-1.5 text-slate-300 font-semibold mb-1">
                            <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                            <span>Veredicto del Risk Engine / Broker</span>
                          </div>
                          {isFilled ? (
                            <p className="text-emerald-400/90 leading-relaxed flex items-start gap-1">
                              <span>✓</span>
                              <span>{trade.risk_verdict.message}</span>
                            </p>
                          ) : (
                            <div className="space-y-1">
                              <p className="text-rose-400/90 font-medium leading-relaxed">
                                {trade.risk_verdict.message}
                              </p>
                              {trade.risk_reasons.length > 0 && (
                                <ul className="list-disc list-inside text-rose-300/80 space-y-0.5 text-[11px]">
                                  {trade.risk_reasons.map((reason, idx) => (
                                    <li key={idx}>{reason}</li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Footer de la Tarjeta */}
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400 pt-2 border-t border-slate-800/40">
                        <div className="flex items-center gap-4">
                          <span className="flex items-center gap-1">
                            <Clock className="h-3 w-3 text-slate-500" />
                            {new Date(trade.timestamp).toLocaleString("es-ES")}
                          </span>
                          {trade.fill_price && (
                            <span className="text-slate-300">
                              Precio Llenado: <strong className="text-white">${trade.fill_price}</strong>
                            </span>
                          )}
                          {trade.order_id && (
                            <span className="text-slate-400 font-mono text-[10px]">
                              Order ID: {trade.order_id}
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setInspectedTrade(trade)}
                            className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1 bg-indigo-950/40 border border-indigo-800/50 px-2.5 py-1 rounded-md transition"
                          >
                            <Eye className="h-3 w-3" />
                            Ver Auditoría JSON
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* PESTAÑA 2: ENDPOINTS DISPONIBLES */}
        {activeTab === "endpoints" && (
          <div className="space-y-4">
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-2">
                <Code2 className="h-5 w-5 text-indigo-400" />
                <h3 className="text-base font-bold text-white">Endpoints Disponibles de la Arquitectura</h3>
              </div>
              <p className="text-xs text-slate-400 max-w-3xl leading-relaxed mb-4">
                El sistema utiliza los endpoints oficiales de Alpaca Paper Trading y las rutas internas de auditoría del agente. 
                Aquí se exponen para verificación y consumo directo:
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {AVAILABLE_API_ENDPOINTS.map((endpoint, i) => (
                  <div
                    key={i}
                    className="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 hover:border-indigo-500/50 transition flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-indigo-950 text-indigo-400 border border-indigo-800/50">
                          {endpoint.category}
                        </span>
                        <span className="text-xs font-mono font-bold bg-emerald-950/80 text-emerald-400 px-2 py-0.5 rounded border border-emerald-800/40">
                          {endpoint.method}
                        </span>
                      </div>
                      <div className="font-mono text-xs font-bold text-white mb-1">
                        {endpoint.path}
                      </div>
                      <p className="text-xs text-slate-400 leading-relaxed">
                        {endpoint.description}
                      </p>
                    </div>

                    <div className="mt-3 pt-2 border-t border-slate-800/60 flex items-center justify-between">
                      <span className="text-[11px] text-slate-500">
                        Estado: <strong className="text-emerald-400">Activo / Live</strong>
                      </span>
                      <button
                        onClick={() => setActiveEndpointModal(endpoint)}
                        className="text-xs text-indigo-400 hover:text-indigo-300 font-medium flex items-center gap-1 bg-indigo-950/30 px-2 py-1 rounded border border-indigo-800/40"
                      >
                        Inspeccionar Datos
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* PESTAÑA 3: AUDITORÍA DE GUARDRAILS DE RIESGO */}
        {activeTab === "risk" && (
          <div className="space-y-4">
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 space-y-4">
              <div className="flex items-center gap-2">
                <ShieldAlert className="h-5 w-5 text-rose-400" />
                <h3 className="text-base font-bold text-white">
                  Reglas de Protección y Prevención de Pérdidas (Risk Engine)
                </h3>
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Cada propuesta generada por el agente autónomo pasa obligatoriamente por una serie de verificaciones deterministas. 
                Si alguna regla falla, la orden es inmediatamente rechazada sin arriesgar capital en Alpaca:
              </p>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3.5 space-y-1.5">
                  <div className="font-bold text-rose-400 flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                    Regla 5% Máximo de Riesgo
                  </div>
                  <p className="text-slate-400 leading-relaxed">
                    Ninguna operación individual puede arriesgar más del 5% del valor total de la cuenta ($5,000 en portafolio de $100k).
                  </p>
                </div>

                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3.5 space-y-1.5">
                  <div className="font-bold text-rose-400 flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                    Spread Bid/Ask Excesivo (&gt; 5%)
                  </div>
                  <p className="text-slate-400 leading-relaxed">
                    Se bloquean contratos con baja liquidez donde el spread supere el 5.0% del precio medio para evitar deslizamiento severo.
                  </p>
                </div>

                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3.5 space-y-1.5">
                  <div className="font-bold text-rose-400 flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                    Bloqueo 0-DTE (Pin Risk)
                  </div>
                  <p className="text-slate-400 leading-relaxed">
                    Se rechaza cualquier opción con 0 días hasta la expiración para evitar riesgo de asignación forzada o pérdida por theta súbito.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Modal de Detalle de Auditoría JSON */}
      {inspectedTrade && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Code2 className="h-4 w-4 text-indigo-400" />
                <h3 className="text-sm font-bold text-white">
                  Auditoría JSON: {inspectedTrade.ticker} ({inspectedTrade.option_symbol})
                </h3>
              </div>
              <button
                onClick={() => setInspectedTrade(null)}
                className="text-slate-400 hover:text-white text-xs bg-slate-800 px-2 py-1 rounded"
              >
                Cerrar
              </button>
            </div>
            <div className="p-4 overflow-y-auto flex-1 font-mono text-xs text-slate-300 bg-slate-950">
              <pre>{JSON.stringify(inspectedTrade, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Endpoint Tester */}
      {activeEndpointModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Code2 className="h-4 w-4 text-emerald-400" />
                <h3 className="text-sm font-bold text-white">
                  Endpoint: {activeEndpointModal.method} {activeEndpointModal.path}
                </h3>
              </div>
              <button
                onClick={() => setActiveEndpointModal(null)}
                className="text-slate-400 hover:text-white text-xs bg-slate-800 px-2 py-1 rounded"
              >
                Cerrar
              </button>
            </div>
            <div className="p-4 text-xs text-slate-400 border-b border-slate-800">
              {activeEndpointModal.description}
            </div>
            <div className="p-4 overflow-y-auto flex-1 font-mono text-xs text-emerald-400 bg-slate-950">
              <pre>
                {activeEndpointModal.path.includes("/v2/account")
                  ? JSON.stringify(account, null, 2)
                  : activeEndpointModal.path.includes("/api/trades")
                  ? JSON.stringify(trades.slice(0, 2), null, 2)
                  : JSON.stringify(
                      {
                        endpoint: activeEndpointModal.path,
                        status: "AVAILABLE",
                        environment: "Alpaca Paper Trading",
                        data_format: "JSON Standard Draft-07",
                      },
                      null,
                      2
                    )}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
