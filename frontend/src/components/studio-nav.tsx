"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

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

  return (
    <nav className="app-nav" aria-label="Main navigation">
      <Link href="/#overview" aria-current={activeSection === "overview" ? "location" : undefined}>Overview</Link>
      <Link href="/#projects" aria-current={activeSection === "projects" ? "location" : undefined}>Projects</Link>
    </nav>
  );
}
