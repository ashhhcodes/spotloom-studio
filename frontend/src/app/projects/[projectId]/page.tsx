import type { Metadata } from "next";
import { Suspense } from "react";
import { ProjectDetailWorkspace } from "../project-workspace";

export const metadata: Metadata = {
  title: "Project — Spotloom Studio",
};

export default function OwnedProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const clerkConfigured = Boolean(
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY,
  );
  return (
    <Suspense fallback={<ProjectPageFallback />}>
      <ResolvedOwnedProjectPage params={params} clerkConfigured={clerkConfigured} />
    </Suspense>
  );
}

async function ResolvedOwnedProjectPage({
  params,
  clerkConfigured,
}: {
  params: Promise<{ projectId: string }>;
  clerkConfigured: boolean;
}) {
  const { projectId } = await params;
  return <ProjectDetailWorkspace clerkConfigured={clerkConfigured} projectId={projectId} />;
}

function ProjectPageFallback() {
  return (
    <div className="projects-workspace">
      <header className="projects-page-heading">
        <div><p className="workspace-kicker">Spotloom Studio · Private workspace</p><h1>Projects for <em>your work.</em></h1></div>
      </header>
      <p className="projects-status" role="status">Opening saved project…</p>
    </div>
  );
}
