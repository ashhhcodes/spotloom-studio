import Link from "next/link";
import { Suspense } from "react";
import { StudioNav } from "@/components/studio-nav";
import { ThemePicker } from "@/components/theme-picker";
import { AuthControlsSlot } from "@/components/auth-controls";
import "./studio-shell.css";

export function StudioShell({ children, clerkConfigured = false }: Readonly<{ children: React.ReactNode; clerkConfigured?: boolean }>) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="app-header">
        <Link className="app-wordmark" href="/" aria-label="Spotloom Studio overview">
          <span className="wordmark-mark" aria-hidden="true"><span /></span>
          <span>Spotloom <span className="wordmark-light">Studio</span></span>
        </Link>
        <Suspense fallback={<StudioNavFallback />}>
          <StudioNav />
        </Suspense>
        <div className="app-header-tools">
          <AuthControlsSlot enabled={clerkConfigured} />
          <ThemePicker />
        </div>
      </header>
      <main id="main-content" className="app-main">{children}</main>
      <footer className="app-footer">
        <span>Spotloom Studio <span aria-hidden="true">·</span> Creative workspace</span>
        <Link href="/design-system">Design system</Link>
      </footer>
    </div>
  );
}

function StudioNavFallback() {
  return (
    <nav className="app-nav" aria-label="Main navigation">
      <Link href="/#overview">Overview</Link>
      <Link href="/#projects">Projects</Link>
    </nav>
  );
}
