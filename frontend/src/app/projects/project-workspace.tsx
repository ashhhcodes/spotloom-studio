"use client";

import { SignInButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  createOwnedProject,
  getOwnedProject,
  listOwnedProjects,
  ProjectApiError,
  PROJECT_NAME_MAX_LENGTH,
  type OwnedProject,
} from "./projects-api";
import "./projects.css";

export function ProjectsWorkspace({ clerkConfigured }: { clerkConfigured: boolean }) {
  if (!clerkConfigured) {
    return <ProjectAccessNotice message="Sign-in is not configured in this local environment. Configure Clerk development settings to manage saved projects." />;
  }
  return <AuthenticatedProjectsWorkspace />;
}

function AuthenticatedProjectsWorkspace() {
  const { isLoaded, isSignedIn, getToken, userId } = useAuth();
  const [loadResult, setLoadResult] = useState<{
    userId: string;
    projects: OwnedProject[];
    error: string;
  } | null>(null);
  const [name, setName] = useState("");
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !userId) return;
    let active = true;
    void listOwnedProjects(getToken).then((records) => {
      if (active) setLoadResult({ userId, projects: records, error: "" });
    }).catch((error: unknown) => {
      if (active) setLoadResult({ userId, projects: [], error: projectErrorMessage(error) });
    });
    return () => { active = false; };
  }, [getToken, isLoaded, isSignedIn, userId]);

  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setNotice("");
    setCreating(true);
    try {
      const created = await createOwnedProject(name, getToken);
      setLoadResult((current) => {
        if (!current || current.userId !== userId) return current;
        return {
          userId: current.userId,
          error: current.error,
          projects: [created, ...current.projects.filter((project) => project.id !== created.id)],
        };
      });
      setName("");
      setNotice(`“${created.name}” was created and is ready to open.`);
    } catch (error) {
      setFormError(projectErrorMessage(error));
    } finally {
      setCreating(false);
    }
  }

  if (!isLoaded) {
    return <ProjectsPageFrame><p className="projects-status" role="status">Loading your projects…</p></ProjectsPageFrame>;
  }
  if (!isSignedIn) {
    return (
      <ProjectsPageFrame>
        <div className="projects-signin-card">
          <p className="workspace-label">Your saved work</p>
          <h2>Sign in to manage projects.</h2>
          <p>Projects are private to the signed-in account. The Northstar sample remains illustrative and separate.</p>
          <SignInButton mode="modal"><button className="projects-primary-action" type="button">Sign in</button></SignInButton>
        </div>
      </ProjectsPageFrame>
    );
  }

  const currentLoad = loadResult?.userId === userId ? loadResult : null;
  if (!currentLoad) {
    return <ProjectsPageFrame><p className="projects-status" role="status">Loading your projects…</p></ProjectsPageFrame>;
  }
  const { projects, error: loadError } = currentLoad;

  return (
    <ProjectsPageFrame>
      <section className="projects-create-card" aria-labelledby="create-project-title">
        <p className="workspace-label">Authenticated workspace</p>
        <h2 id="create-project-title">Start a saved project.</h2>
        <p>Only the project name is sent. Spotloom assigns the project ID and owner from your verified session.</p>
        <form className="projects-create-form" onSubmit={submitProject}>
          <label htmlFor="owned-project-name">Project name</label>
          <div className="projects-create-row">
            <input
              id="owned-project-name"
              value={name}
              onChange={(event) => { setName(event.target.value); setFormError(""); setNotice(""); }}
              required
              autoComplete="off"
              aria-invalid={formError ? true : undefined}
              aria-describedby="project-name-help"
            />
              <button className="projects-primary-action" type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create project"}
            </button>
          </div>
          <p className="projects-help" id="project-name-help">Names are trimmed and limited to {PROJECT_NAME_MAX_LENGTH} characters under a provisional engineering bound.</p>
          {formError && <p className="projects-message projects-message-error" role="alert">{formError}</p>}
          {notice && <p className="projects-message" role="status">{notice}</p>}
        </form>
      </section>

      <section className="projects-list-section" aria-labelledby="owned-projects-title">
        <div className="projects-list-heading">
          <div><p className="workspace-label">Private to your account</p><h2 id="owned-projects-title">Saved projects</h2></div>
          <span>{projects.length} {projects.length === 1 ? "project" : "projects"}</span>
        </div>
        {loadError && <p className="projects-message projects-message-error" role="alert">{loadError}</p>}
        {!loadError && projects.length === 0 && (
          <p className="projects-empty">No saved projects yet. Create one above to begin. The Northstar sample is not included here.</p>
        )}
        {projects.length > 0 && (
          <ul className="owned-project-list">
            {projects.map((project) => (
              <li className="owned-project-card" key={project.id}>
                <div><small>Saved project</small><h3>{project.name}</h3><p>Project record · {project.id}</p></div>
                <Link className="projects-open-link" href={`/projects/${encodeURIComponent(project.id)}`}>Open project <span aria-hidden="true">↗</span></Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <p className="projects-boundary-note">Saved project records are persistent. Briefs, facts, storyboards, and render state are not saved by this milestone. Northstar remains an illustrative demo.</p>
    </ProjectsPageFrame>
  );
}

export function ProjectDetailWorkspace({
  clerkConfigured,
  projectId,
}: {
  clerkConfigured: boolean;
  projectId: string;
}) {
  if (!clerkConfigured) {
    return <ProjectAccessNotice message="Sign-in is not configured in this local environment, so saved project records cannot be opened." />;
  }
  return <AuthenticatedProjectDetail projectId={projectId} />;
}

function AuthenticatedProjectDetail({ projectId }: { projectId: string }) {
  const { isLoaded, isSignedIn, getToken, userId } = useAuth();
  const [loadResult, setLoadResult] = useState<{
    key: string;
    project: OwnedProject | null;
    error: string;
  } | null>(null);
  const loadKey = `${userId ?? ""}:${projectId}`;

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !userId) return;
    let active = true;
    void getOwnedProject(projectId, getToken).then((record) => {
      if (active) setLoadResult({ key: `${userId}:${projectId}`, project: record, error: "" });
    }).catch((reason: unknown) => {
      if (active) setLoadResult({ key: `${userId}:${projectId}`, project: null, error: projectErrorMessage(reason) });
    });
    return () => { active = false; };
  }, [getToken, isLoaded, isSignedIn, projectId, userId]);

  if (!isLoaded) {
    return <ProjectsPageFrame><p className="projects-status" role="status">Opening saved project…</p></ProjectsPageFrame>;
  }
  if (!isSignedIn) {
    return (
      <ProjectsPageFrame>
        <div className="projects-signin-card"><p className="workspace-label">Private project</p><h2>Sign in to open this project.</h2><SignInButton mode="modal"><button className="projects-primary-action" type="button">Sign in</button></SignInButton></div>
      </ProjectsPageFrame>
    );
  }

  const currentLoad = loadResult?.key === loadKey ? loadResult : null;
  if (!currentLoad) {
    return <ProjectsPageFrame><p className="projects-status" role="status">Opening saved project…</p></ProjectsPageFrame>;
  }
  const { project, error } = currentLoad;

  return (
    <ProjectsPageFrame>
      <Link className="projects-back-link" href="/projects">← Back to saved projects</Link>
      {error
        ? <p className="projects-message projects-message-error" role="alert">{error}</p>
        : project && (
          <section className="projects-detail-card" aria-labelledby="owned-project-title">
            <p className="workspace-label">Authenticated project record</p>
            <h2 id="owned-project-title">{project.name}</h2>
            <dl><div><dt>Project ID</dt><dd>{project.id}</dd></div><div><dt>Created</dt><dd>{formatDate(project.createdAt)}</dd></div></dl>
            <p>Project access was checked by the backend. Project briefs, facts, storyboards, and render state are not included in this saved record yet.</p>
          </section>
        )}
    </ProjectsPageFrame>
  );
}

function ProjectsPageFrame({ children }: { children: ReactNode }) {
  return (
    <div className="projects-workspace">
      <header className="projects-page-heading">
        <div><p className="workspace-kicker">Spotloom Studio · Private workspace</p><h1>Projects for <em>your work.</em></h1><p>Create and open project records tied to your signed-in account.</p></div>
        <span className="workspace-index">WORKSPACE / PROJECTS</span>
      </header>
      {children}
    </div>
  );
}

function ProjectAccessNotice({ message }: { message: string }) {
  return <ProjectsPageFrame><p className="projects-message projects-message-error" role="status">{message}</p></ProjectsPageFrame>;
}

function projectErrorMessage(error: unknown): string {
  return error instanceof ProjectApiError
    ? error.message
    : "The project service could not complete the request. Try again later.";
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unavailable" : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(parsed);
}
