import { NextResponse } from "next/server";
import { getLiveTrades } from "@/lib/tradeLogParser";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const ticker = searchParams.get("ticker");
  const status = searchParams.get("status");
  const assetClass = searchParams.get("assetClass");

  const { trades, source } = getLiveTrades();
  let filtered = [...trades];

  if (ticker && ticker !== "ALL") {
    filtered = filtered.filter((t) => t.ticker.toUpperCase() === ticker.toUpperCase());
  }

  if (status && status !== "ALL") {
    filtered = filtered.filter((t) => t.execution_status === status);
  }

  if (assetClass && assetClass !== "ALL") {
    filtered = filtered.filter((t) => t.asset_class === assetClass);
  }

  return NextResponse.json({
    total: filtered.length,
    trades: filtered,
    source,
  });
}
