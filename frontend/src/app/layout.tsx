import type { Metadata, Viewport } from "next";
import { ClerkProvider } from "@clerk/nextjs";
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
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const clerkConfigured = Boolean(publishableKey && process.env.CLERK_SECRET_KEY);
  const shell = <StudioShell clerkConfigured={clerkConfigured}>{children}</StudioShell>;

  return (
    <html lang="en" data-theme="system">
      <body>
        {clerkConfigured && publishableKey
          ? <ClerkProvider publishableKey={publishableKey}>{shell}</ClerkProvider>
          : shell}
      </body>
    </html>
  );
}
