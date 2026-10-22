import Link from "next/link";
import { StudioNav } from "@/components/studio-nav";
import { ThemePicker } from "@/components/theme-picker";
import "./studio-shell.css";

export function StudioShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="app-header">
        <Link className="app-wordmark" href="/" aria-label="Spotloom Studio overview">
          <span className="wordmark-mark" aria-hidden="true"><span /></span>
          <span>Spotloom <span className="wordmark-light">Studio</span></span>
        </Link>
        <StudioNav />
        <ThemePicker />
      </header>
      <main id="main-content" className="app-main">{children}</main>
      <footer className="app-footer">
        <span>Spotloom Studio <span aria-hidden="true">·</span> Creative workspace</span>
        <Link href="/design-system">Design system</Link>
      </footer>
    </div>
  );
}
