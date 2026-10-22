import type { Metadata, Viewport } from "next";
import { StudioShell } from "@/components/studio-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Spotloom Studio — Creative workspace",
  description: "Plan and shape clear campaign work for your business.",
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
      <body><StudioShell>{children}</StudioShell></body>
    </html>
  );
}
