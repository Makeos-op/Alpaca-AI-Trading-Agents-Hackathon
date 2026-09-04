import { NextResponse } from "next/server";
import { DEFAULT_ACCOUNT_SNAPSHOT } from "@/data/historicalTrades";

export const dynamic = "force-dynamic";

export async function GET() {
  const apiKey = process.env.APCA_API_KEY_ID || process.env.API_KEY;
  const secretKey = process.env.APCA_API_SECRET_KEY || process.env.SECRET_KEY;
  const baseUrl = process.env.APCA_API_BASE_URL || "https://paper-api.alpaca.markets";

  if (apiKey && secretKey) {
    try {
      const res = await fetch(`${baseUrl}/v2/account`, {
        headers: {
          "APCA-API-KEY-ID": apiKey,
          "APCA-API-SECRET-KEY": secretKey,
        },
        cache: "no-store",
      });

      if (res.ok) {
        const data = await res.json();
        return NextResponse.json({
          live: true,
          endpoint: `${baseUrl}/v2/account`,
          account: {
            account_id: data.id || data.account_number,
            status: data.status,
            cash: data.cash,
            portfolio_value: data.portfolio_value,
            buying_power: data.buying_power,
            equity: data.equity,
            daytrading_buying_power: data.daytrading_buying_power || data.buying_power,
            daytrading_count: data.daytrade_count || 0,
            is_daytrader: Boolean(data.pattern_day_trader),
            is_active: data.status === "ACTIVE",
            currency: data.currency || "USD",
          },
        });
      }
    } catch {
      // Fallback a snapshot verificado si hay error de red
    }
  }

  return NextResponse.json({
    live: false,
    endpoint: "/v2/account (Paper Snapshot)",
    account: DEFAULT_ACCOUNT_SNAPSHOT,
    notice: "Operando con snapshot auditado de cuenta. Para sincronización en vivo con Alpaca Paper, configure APCA_API_KEY_ID y APCA_API_SECRET_KEY en Vercel.",
  });
}

