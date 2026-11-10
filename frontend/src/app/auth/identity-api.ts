export type VerifiedBackendIdentity = {
  issuer: string;
  subject: string;
};

export type IdentityCheckErrorKind =
  | "missing-token"
  | "token-unavailable"
  | "network"
  | "unauthorized"
  | "backend-not-configured"
  | "backend-error"
  | "invalid-response";

export class IdentityCheckError extends Error {
  readonly kind: IdentityCheckErrorKind;

  constructor(kind: IdentityCheckErrorKind, message: string) {
    super(message);
    this.name = "IdentityCheckError";
    this.kind = kind;
  }
}

const endpoint = "/api/adforge/auth/identity";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function verifyBackendIdentity(
  getSessionToken: () => Promise<string | null>,
  fetcher: typeof fetch = fetch,
): Promise<VerifiedBackendIdentity> {
  let token: string | null;
  try {
    token = await getSessionToken();
  } catch {
    throw new IdentityCheckError("token-unavailable", "The Clerk session token could not be retrieved. Try again.");
  }
  if (!token) {
    throw new IdentityCheckError("missing-token", "No Clerk session token is available. Sign in again and retry.");
  }

  let response: Response;
  try {
    response = await fetcher(endpoint, {
      method: "GET",
      headers: { accept: "application/json", authorization: `Bearer ${token}` },
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    throw new IdentityCheckError("network", "The Spotloom backend is unavailable. Start it and retry.");
  }

  if (response.status === 401) {
    throw new IdentityCheckError("unauthorized", "The backend did not accept this Clerk session. Refresh your sign-in and retry.");
  }
  if (response.status === 503) {
    throw new IdentityCheckError("backend-not-configured", "Backend Clerk verification is not configured yet.");
  }
  if (!response.ok) {
    throw new IdentityCheckError("backend-error", "The backend could not verify this session. Try again later.");
  }

  let decoded: unknown;
  try {
    decoded = await response.json();
  } catch {
    throw new IdentityCheckError("invalid-response", "The backend returned an unreadable identity response.");
  }
  if (!isRecord(decoded)
    || decoded.authenticated !== true
    || !isRecord(decoded.principal)
    || typeof decoded.principal.issuer !== "string"
    || decoded.principal.issuer.length === 0
    || typeof decoded.principal.subject !== "string"
    || decoded.principal.subject.length === 0) {
    throw new IdentityCheckError("invalid-response", "The backend returned an unexpected identity response.");
  }

  return { issuer: decoded.principal.issuer, subject: decoded.principal.subject };
}
