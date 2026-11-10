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
  | "conflict"
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
  if (response.status === 409) {
    throw new ProjectApiError("conflict", "This project workspace changed since it was loaded. Reload it before saving again.");
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

export type ProjectCampaignBrief = {
  campaign_name: string;
  brand_name: string;
  website_url: string;
  product_or_service: string;
  target_audience: string;
  objective: "awareness" | "engagement" | "traffic" | "conversions" | null;
  platform: "instagram" | "tiktok" | "youtube" | "other" | null;
  key_selling_points: string[];
  call_to_action: string;
};

export type ProjectCreativeDirection = {
  visual_style: string;
  advertising_tone: string;
  primary_message: string;
  supporting_message: string;
  audience_emphasis: string;
  brand_personality: string;
  desired_video_format: "9:16" | "1:1" | "16:9" | null;
  preferred_duration_seconds: 15 | 30 | 60 | null;
};

export type ProjectStoryboardScene = {
  id: string;
  title: string;
  description: string;
  visual_direction: string;
  on_screen_text: string;
  narration: string;
  duration_seconds: number;
  status: "draft" | "ready_for_review";
};

export type ProjectCreativeWorkspace = {
  project_id: string;
  revision: number;
  brief: ProjectCampaignBrief;
  creative_direction: ProjectCreativeDirection;
  storyboard: ProjectStoryboardScene[];
  created_at: string | null;
  updated_at: string | null;
};

export type ProjectCreativeWorkspaceUpdate = Pick<ProjectCreativeWorkspace,
  "revision" | "brief" | "creative_direction" | "storyboard"
>;

function parseWorkspace(value: unknown, expectedProjectId?: string): ProjectCreativeWorkspace | null {
  if (!isRecord(value)
    || typeof value.project_id !== "string"
    || (expectedProjectId !== undefined && value.project_id !== expectedProjectId)
    || !Number.isInteger(value.revision)
    || Number(value.revision) < 0
    || typeof value.brief !== "object" || value.brief === null
    || typeof value.creative_direction !== "object" || value.creative_direction === null
    || !Array.isArray(value.storyboard)
    || !(value.created_at === null || typeof value.created_at === "string")
    || !(value.updated_at === null || typeof value.updated_at === "string")) return null;
  const brief = value.brief as Record<string, unknown>;
  const direction = value.creative_direction as Record<string, unknown>;
  const storyboard = value.storyboard as unknown[];
  const textFields = ["campaign_name", "brand_name", "website_url", "product_or_service", "target_audience", "call_to_action"];
  if (textFields.some((field) => typeof brief[field] !== "string")
    || !Array.isArray(brief.key_selling_points)
    || !brief.key_selling_points.every((point) => typeof point === "string")
    || !(brief.objective === null || ["awareness", "engagement", "traffic", "conversions"].includes(String(brief.objective)))
    || !(brief.platform === null || ["instagram", "tiktok", "youtube", "other"].includes(String(brief.platform)))) return null;
  const directionTextFields = ["visual_style", "advertising_tone", "primary_message", "supporting_message", "audience_emphasis", "brand_personality"];
  if (directionTextFields.some((field) => typeof direction[field] !== "string")
    || !(direction.desired_video_format === null || ["9:16", "1:1", "16:9"].includes(String(direction.desired_video_format)))
    || !(direction.preferred_duration_seconds === null || [15, 30, 60].includes(Number(direction.preferred_duration_seconds)))) return null;
  const scenes = storyboard.map((scene) => {
    if (!isRecord(scene)
      || typeof scene.id !== "string"
      || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(scene.id)
      || typeof scene.title !== "string"
      || !scene.title.trim()
      || scene.title.length > 120
      || typeof scene.description !== "string"
      || scene.description.length > 500
      || typeof scene.visual_direction !== "string"
      || scene.visual_direction.length > 1000
      || typeof scene.on_screen_text !== "string"
      || scene.on_screen_text.length > 500
      || typeof scene.narration !== "string"
      || scene.narration.length > 1000
      || !Number.isInteger(scene.duration_seconds)
      || Number(scene.duration_seconds) < 1 || Number(scene.duration_seconds) > 60
      || !(scene.status === "draft" || scene.status === "ready_for_review")) return null;
    return scene as unknown as ProjectStoryboardScene;
  });
  if (scenes.some((scene) => scene === null)
    || new Set(scenes.map((scene) => scene?.id)).size !== scenes.length
    || scenes.length > 32) return null;
  return value as unknown as ProjectCreativeWorkspace;
}

export async function getOwnedProjectCreativeWorkspace(
  projectId: string,
  getSessionToken: GetSessionToken,
  fetcher: typeof fetch = fetch,
): Promise<ProjectCreativeWorkspace> {
  const decoded = await requestJson(
    `${projectsEndpoint}/${encodeURIComponent(projectId)}/creative-workspace`,
    getSessionToken,
    fetcher,
    { method: "GET" },
  );
  const workspace = parseWorkspace(decoded, projectId);
  if (!workspace) throw new ProjectApiError("invalid-response", "The project service returned an unexpected workspace response.");
  return workspace;
}

export async function saveOwnedProjectCreativeWorkspace(
  projectId: string,
  workspace: ProjectCreativeWorkspaceUpdate,
  getSessionToken: GetSessionToken,
  fetcher: typeof fetch = fetch,
): Promise<ProjectCreativeWorkspace> {
  const decoded = await requestJson(
    `${projectsEndpoint}/${encodeURIComponent(projectId)}/creative-workspace`,
    getSessionToken,
    fetcher,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(workspace),
    },
  );
  const saved = parseWorkspace(decoded, projectId);
  if (!saved) throw new ProjectApiError("invalid-response", "The project service returned an unexpected workspace response.");
  return saved;
}
