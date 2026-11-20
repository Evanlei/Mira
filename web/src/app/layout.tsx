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
  themeColor: "#1c1c1f",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${figtree.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        {children}
        {/* Dev-only visual feedback toolbar (manual copy mode: notes stay in this browser). */}
        {process.env.NODE_ENV === "development" && <Agentation />}
      </body>
    </html>
  );
}
