import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Spotloom Studio — Design foundation",
  description: "The visual foundation for Spotloom Studio.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F3EFE7" },
    { media: "(prefers-color-scheme: dark)", color: "#191A18" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-theme="system">
      <body>{children}</body>
    </html>
  );
}
