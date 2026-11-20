import type { Metadata, Viewport } from "next";
import { Figtree } from "next/font/google";
import { Agentation } from "agentation";

import "./globals.css";

const figtree = Figtree({
  variable: "--font-figtree",
  subsets: ["latin"],
  display: "swap",
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
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${figtree.variable} h-full antialiased`}>
      {/* suppressHydrationWarning: extensions like Grammarly add attributes to <body> before React loads. */}
      <body className="flex min-h-full flex-col" suppressHydrationWarning>
        {children}
        {/* Dev-only visual feedback toolbar (manual copy mode: notes stay in this browser). */}
        {process.env.NODE_ENV === "development" && <Agentation />}
      </body>
    </html>
  );
}
