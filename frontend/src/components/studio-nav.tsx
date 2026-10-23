"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type MouseEvent } from "react";

type WorkspaceSection = "overview" | "projects" | null;

export function StudioNav() {
  const pathname = usePathname();
  const [activeSection, setActiveSection] = useState<WorkspaceSection>(null);

  useEffect(() => {
    const syncLocation = () => {
      if (window.location.pathname !== "/") {
        setActiveSection(null);
      } else {
        setActiveSection(window.location.hash === "#projects" ? "projects" : "overview");
      }
    };
    syncLocation();
    window.addEventListener("hashchange", syncLocation);
    window.addEventListener("popstate", syncLocation);
    return () => {
      window.removeEventListener("hashchange", syncLocation);
      window.removeEventListener("popstate", syncLocation);
    };
  }, [pathname]);

  function selectSection(section: Exclude<WorkspaceSection, null>, event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    setActiveSection(section);
  }

  return (
    <nav className="app-nav" aria-label="Main navigation">
      <Link href="/#overview" onClick={(event) => selectSection("overview", event)} aria-current={pathname === "/" && activeSection === "overview" ? "location" : undefined}>Overview</Link>
      <Link href="/#projects" onClick={(event) => selectSection("projects", event)} aria-current={pathname === "/" && activeSection === "projects" ? "location" : undefined}>Projects</Link>
    </nav>
  );
}
