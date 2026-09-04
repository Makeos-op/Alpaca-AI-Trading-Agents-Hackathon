import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Infrangible | Alpaca AI Trading Dashboard",
  description: "Estadísticas, identificación de activos, razonamiento del agente autónomo de trading y auditoría de riesgo 5% con Alpaca Paper Trading.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className="dark">
      <body className="bg-[#0b0f19] text-slate-100 antialiased selection:bg-indigo-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}

