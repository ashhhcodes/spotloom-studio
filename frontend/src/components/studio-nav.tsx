"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export function StudioNav() {
  const pathname = usePathname();
  const [projectsActive, setProjectsActive] = useState(false);

  useEffect(() => {
    const syncHash = () => setProjectsActive(window.location.hash === "#projects");
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, [pathname]);

  return (
    <nav className="app-nav" aria-label="Main navigation">
      <Link href="/" aria-current={pathname === "/" && !projectsActive ? "page" : undefined}>Overview</Link>
      <Link href="/#projects" aria-current={pathname === "/" && projectsActive ? "location" : undefined}>Projects</Link>
    </nav>
  );
}
