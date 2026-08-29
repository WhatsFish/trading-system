import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";

const UMAMI_SRC = process.env.NEXT_PUBLIC_UMAMI_SRC;
const UMAMI_ID = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;

export const metadata: Metadata = {
  title: "Trading System — ai-native",
  description: "Private, risk-first trading research and operations dashboard.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-50 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100 antialiased">
        {UMAMI_SRC && UMAMI_ID ? (
          <Script
            defer
            src={UMAMI_SRC}
            data-website-id={UMAMI_ID}
            strategy="afterInteractive"
          />
        ) : null}
        {children}
      </body>
    </html>
  );
}

