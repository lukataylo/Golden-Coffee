import type { Metadata, Viewport } from "next";
import { Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { clerkAppearance } from "@/lib/clerk-appearance";
import { env } from "@/lib/env";
import "./globals.css";

const sans = Hanken_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
  weight: ["300", "400", "500", "600", "700", "800"],
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  metadataBase: new URL(env.appUrl),
  title: {
    default: "Golden Coffee — your café, but it runs itself",
    template: "%s · Golden Coffee",
  },
  description:
    "An ambient + ops copilot for cafés and restaurants. Privacy-first, runs on a single existing camera.",
  applicationName: "Golden Coffee",
  openGraph: {
    title: "Golden Coffee",
    description: "Your café, but it runs itself.",
    type: "website",
    siteName: "Golden Coffee",
  },
  icons: { icon: "/favicon.ico" },
};

export const viewport: Viewport = {
  themeColor: "#161009",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const html = (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
  // Only mount ClerkProvider when a publishable key is configured. Without it,
  // ClerkProvider throws during static prerender ("Missing publishableKey") and
  // breaks `next build` — so the marketing site can deploy to Vercel with zero
  // config, and full auth lights up the moment the key is set.
  if (!env.clerkEnabled) return html;
  return <ClerkProvider appearance={clerkAppearance}>{html}</ClerkProvider>;
}
