export type OwnedProject = {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
};

export type ProjectApiErrorKind =
  | "missing-token"
  | "token-unavailable"
  | "network"
  | "unauthorized"
  | "not-found"
  | "invalid-name"
  | "invalid-request"
  | "backend-error"
  | "invalid-response";

export class ProjectApiError extends Error {
  readonly kind: ProjectApiErrorKind;

  constructor(kind: ProjectApiErrorKind, message: string) {
    super(message);
    this.name = "ProjectApiError";
    this.kind = kind;
  }
}

export const PROJECT_NAME_MAX_LENGTH = 120;
const projectsEndpoint = "/api/adforge/projects";

type GetSessionToken = () => Promise<string | null>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseProject(value: unknown): OwnedProject | null {
  if (!isRecord(value)
    || typeof value.id !== "string"
    || typeof value.name !== "string"
    || typeof value.created_at !== "string"
    || typeof value.updated_at !== "string") {
    return null;
  }
  return {
    id: value.id,
    name: value.name,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

async function requestJson(
  path: string,
  getSessionToken: GetSessionToken,
  fetcher: typeof fetch,
  init: RequestInit,
): Promise<unknown> {
  let token: string | null;
  try {
    token = await getSessionToken();
  } catch {
    throw new ProjectApiError("token-unavailable", "The sign-in token could not be retrieved. Try again.");
  }
  if (!token) {
    throw new ProjectApiError("missing-token", "Sign in to access your projects.");
  }

  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  headers.set("authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetcher(path, {
      ...init,
      headers,
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    throw new ProjectApiError("network", "Spotloom could not reach the project service. Check that it is running and retry.");
  }

  if (response.status === 401) {
    throw new ProjectApiError("unauthorized", "Your session was not accepted. Sign in again and retry.");
  }
  if (response.status === 404) {
    throw new ProjectApiError("not-found", "Project not found or unavailable to this account.");
  }
  if (response.status === 422) {
    throw new ProjectApiError("invalid-request", "The project request was invalid. Check the project name or link and try again.");
  }
  if (!response.ok) {
    throw new ProjectApiError("backend-error", "The project service could not complete the request. Try again later.");
  }

  try {
    return await response.json() as unknown;
  } catch {
    throw new ProjectApiError("invalid-response", "The project service returned an unreadable response.");
  }
}

export async function listOwnedProjects(
  getSessionToken: GetSessionToken,
  fetcher: typeof fetch = fetch,
): Promise<OwnedProject[]> {
  const decoded = await requestJson(projectsEndpoint, getSessionToken, fetcher, { method: "GET" });
  if (!Array.isArray(decoded)) {
    throw new ProjectApiError("invalid-response", "The project service returned an unexpected list response.");
  }
  const projects = decoded.map(parseProject);
  if (projects.some((project) => project === null)) {
    throw new ProjectApiError("invalid-response", "The project service returned an unexpected project record.");
  }
  return projects as OwnedProject[];
}

export async function createOwnedProject(
  name: string,
  getSessionToken: GetSessionToken,
  fetcher: typeof fetch = fetch,
): Promise<OwnedProject> {
  const normalizedName = name.trim();
  if (!normalizedName || Array.from(normalizedName).length > PROJECT_NAME_MAX_LENGTH) {
    throw new ProjectApiError(
      "invalid-name",
      `Enter a project name between 1 and ${PROJECT_NAME_MAX_LENGTH} characters. This limit is provisional.`,
    );
  }
  const decoded = await requestJson(projectsEndpoint, getSessionToken, fetcher, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: normalizedName }),
  });
  const project = parseProject(decoded);
  if (!project) {
    throw new ProjectApiError("invalid-response", "The project service returned an unexpected project record.");
  }
  return project;
}

export async function getOwnedProject(
  projectId: string,
  getSessionToken: GetSessionToken,
  fetcher: typeof fetch = fetch,
): Promise<OwnedProject> {
  const decoded = await requestJson(
    `${projectsEndpoint}/${encodeURIComponent(projectId)}`,
    getSessionToken,
    fetcher,
    { method: "GET" },
  );
  const project = parseProject(decoded);
  if (!project) {
    throw new ProjectApiError("invalid-response", "The project service returned an unexpected project record.");
  }
  return project;
}
