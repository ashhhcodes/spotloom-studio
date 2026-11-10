import type { Metadata } from "next";
import { ProjectsWorkspace } from "./project-workspace";

export const metadata: Metadata = {
  title: "Saved projects — Spotloom Studio",
  description: "Create and open private Spotloom project records.",
};

export default function ProjectsPage() {
  const clerkConfigured = Boolean(
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY,
  );
  return <ProjectsWorkspace clerkConfigured={clerkConfigured} />;
}
