export type ProductionPackageIssue = {
  path: string;
  code: string;
  message: string;
};

export type ProductionPackagePreflightResult = {
  outcome: "evaluated" | "schema-invalid" | "unsupported" | "request-error";
  correlationId: string | null;
  structurallyValid: boolean | null;
  issues: ProductionPackageIssue[];
  contractVersion?: string;
  rendererProfileId?: string;
};

export type ProductionPackagePreflightErrorKind =
  | "invalid-json"
  | "unsupported-version"
  | "unavailable"
  | "invalid-response"
  | "server-error";

export class ProductionPackagePreflightError extends Error {
  readonly kind: ProductionPackagePreflightErrorKind;

  constructor(kind: ProductionPackagePreflightErrorKind, message: string) {
    super(message);
    this.kind = kind;
    this.name = "ProductionPackagePreflightError";
  }
}

const endpoint = "/api/adforge/validate/production-package";
const v2Contract = "spotloom.production-package.v2";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const safePathPattern = /^[A-Za-z0-9_.\[\]-]*$/;
const safeCodePattern = /^[a-z0-9_]{1,80}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isIssue(value: unknown): value is ProductionPackageIssue {
  return isRecord(value)
    && typeof value.path === "string"
    && value.path.length <= 180
    && safePathPattern.test(value.path)
    && typeof value.code === "string"
    && safeCodePattern.test(value.code)
    && typeof value.message === "string"
    && value.message.length > 0
    && value.message.length <= 300
    && !/[\u0000-\u001f\u007f]/.test(value.message);
}

function parseV2Input(raw: string): { correlationId: string | null } {
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    throw new ProductionPackagePreflightError("invalid-json", "Enter valid JSON before requesting validation.");
  }

  if (!isRecord(decoded)) {
    throw new ProductionPackagePreflightError("invalid-json", "The package must be a JSON object.");
  }
  if (decoded.contractVersion !== v2Contract) {
    throw new ProductionPackagePreflightError(
      "unsupported-version",
      "This screen accepts only spotloom.production-package.v2. V1 packages are not version-pinned for future asset use.",
    );
  }

  return {
    correlationId: typeof decoded.correlationId === "string" && uuidPattern.test(decoded.correlationId)
      ? decoded.correlationId
      : null,
  };
}

function parseResponse(value: unknown, expectedCorrelationId: string | null, status: number): ProductionPackagePreflightResult {
  if (!isRecord(value)
    || !["evaluated", "schema-invalid", "unsupported", "request-error"].includes(String(value.outcome))
    || !(value.correlationId === null || (typeof value.correlationId === "string" && uuidPattern.test(value.correlationId)))
    || !(value.structurallyValid === null || typeof value.structurallyValid === "boolean")
    || !Array.isArray(value.issues)
    || !value.issues.every(isIssue)) {
    throw new ProductionPackagePreflightError("invalid-response", "The backend returned an unreadable validation response.");
  }

  const outcome = value.outcome as ProductionPackagePreflightResult["outcome"];
  if (expectedCorrelationId && value.correlationId !== null && value.correlationId !== expectedCorrelationId) {
    throw new ProductionPackagePreflightError("invalid-response", "The backend response did not match this package evaluation.");
  }

  if (outcome === "evaluated") {
    if (status !== 200
      || value.contractVersion !== v2Contract
      || typeof value.rendererProfileId !== "string"
      || value.rendererProfileId.length === 0
      || value.rendererProfileId.length > 120
      || typeof value.structurallyValid !== "boolean"
      || (value.structurallyValid && value.issues.length !== 0)
      || (!value.structurallyValid && value.issues.length === 0)
      || !value.correlationId
      || value.correlationId !== expectedCorrelationId) {
      throw new ProductionPackagePreflightError("invalid-response", "The backend returned an unexpected validation result.");
    }
    return {
      outcome,
      correlationId: value.correlationId,
      contractVersion: v2Contract,
      rendererProfileId: value.rendererProfileId,
      structurallyValid: value.structurallyValid,
      issues: value.issues,
    };
  }

  if ((outcome === "schema-invalid" || outcome === "unsupported") && status !== 422) {
    throw new ProductionPackagePreflightError("invalid-response", "The backend returned an unexpected validation result.");
  }
  if (outcome === "request-error" && (status < 400 || status >= 500 || value.issues.length === 0)) {
    throw new ProductionPackagePreflightError("invalid-response", "The backend returned an unexpected validation result.");
  }
  if (outcome !== "request-error" && status < 400) {
    throw new ProductionPackagePreflightError("invalid-response", "The backend returned an unexpected validation result.");
  }

  return {
    outcome,
    correlationId: value.correlationId,
    structurallyValid: null,
    issues: value.issues,
  };
}

export async function requestProductionPackagePreflight(
  raw: string,
  fetcher: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<ProductionPackagePreflightResult> {
  const { correlationId } = parseV2Input(raw);
  try {
    const response = await fetcher(endpoint, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: raw,
      cache: "no-store",
      redirect: "error",
      signal,
    });
    let decoded: unknown;
    try {
      decoded = await response.json();
    } catch {
      throw new ProductionPackagePreflightError("invalid-response", "The backend returned an unreadable validation response.");
    }

    if (response.status >= 500) {
      throw new ProductionPackagePreflightError("server-error", "The backend could not complete package validation. Try again later.");
    }
    return parseResponse(decoded, correlationId, response.status);
  } catch (error) {
    if (error instanceof ProductionPackagePreflightError) throw error;
    if (signal?.aborted || (error instanceof Error && error.name === "AbortError")) throw error;
    throw new ProductionPackagePreflightError("unavailable", "The local/demo validation backend is unavailable. Start it and retry.");
  }
}
