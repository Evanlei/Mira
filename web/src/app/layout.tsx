import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Agentation } from "agentation";

import { DisableThemeTransitions } from "@/components/disable-theme-transitions";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Mira · Brawl Stars draft coach",
  description: "Pick and ban suggestions for Brawl Stars Ranked, learned from all-Masters matches.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfd" },
    { media: "(prefers-color-scheme: dark)", color: "#16171d" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-sans">
        <DisableThemeTransitions />
        {children}
        {/* Dev-only visual feedback toolbar (manual copy mode: notes stay in this browser). */}
        {process.env.NODE_ENV === "development" && <Agentation />}
      </body>
    </html>
  );
}
