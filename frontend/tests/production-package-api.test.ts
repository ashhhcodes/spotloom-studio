import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const {
  requestProductionPackagePreflight,
} = await import(new URL("../src/app/projects/sample-northstar/package/production-package-api.ts", import.meta.url).href);

const validPackage = readFileSync(
  new URL("../../backend/tests/fixtures/production-package-v2-valid.json", import.meta.url),
  "utf8",
);
const parsedPackage = JSON.parse(validPackage) as { correlationId: string; rendererProfileId: string };

function successfulResponse() {
  return {
    outcome: "evaluated",
    correlationId: parsedPackage.correlationId,
    contractVersion: "spotloom.production-package.v2",
    rendererProfileId: parsedPackage.rendererProfileId,
    structurallyValid: true,
    issues: [],
  };
}

function responseFor(value: unknown, status = 200): typeof fetch {
  return async () => new Response(JSON.stringify(value), { status });
}

function isPreflightError(error: unknown, kind: string): error is Error & { kind: string } {
  return error instanceof Error
    && error.name === "ProductionPackagePreflightError"
    && (error as Error & { kind?: unknown }).kind === kind;
}

test("explicit request posts the unchanged v2 JSON to the same-origin endpoint", async () => {
  let calls = 0;
  let requestUrl: RequestInfo | URL | undefined;
  let requestInit: RequestInit | undefined;
  const result = await requestProductionPackagePreflight(validPackage, async (input: RequestInfo | URL, init?: RequestInit) => {
    calls += 1;
    requestUrl = input;
    requestInit = init;
    return new Response(JSON.stringify(successfulResponse()), { status: 200 });
  });

  assert.equal(calls, 1);
  assert.equal(requestUrl, "/api/adforge/validate/production-package");
  assert.equal(requestInit?.method, "POST");
  assert.equal(new Headers(requestInit?.headers).get("content-type"), "application/json");
  assert.equal(requestInit?.cache, "no-store");
  assert.equal(requestInit?.redirect, "error");
  assert.equal(requestInit?.body, validPackage);
  assert.equal(result.structurallyValid, true);
});

test("invalid JSON is rejected safely without sending a request", async () => {
  let calls = 0;
  await assert.rejects(
    requestProductionPackagePreflight("{ not json", async () => {
      calls += 1;
      return new Response();
    }),
    (error: unknown) => isPreflightError(error, "invalid-json")
      && !error.message.includes("not json"),
  );
  assert.equal(calls, 0);
});

test("v1, missing, and unknown contract versions fail as v2-only input without network calls", async () => {
  let calls = 0;
  for (const packageText of [
    JSON.stringify({ ...parsedPackage, contractVersion: "spotloom.production-package.v1" }),
    JSON.stringify({ projectId: "sample" }),
    JSON.stringify({ ...parsedPackage, contractVersion: "spotloom.production-package.v3" }),
  ]) {
    await assert.rejects(
      requestProductionPackagePreflight(packageText, async () => {
        calls += 1;
        return new Response();
      }),
      (error: unknown) => isPreflightError(error, "unsupported-version"),
    );
  }
  assert.equal(calls, 0);
});

test("schema-invalid findings from a 422 response are returned for display", async () => {
  const finding = {
    path: "assets.0.assetVersionId",
    code: "package_schema_invalid",
    message: "Value does not match the supported production package contract.",
  };
  const result = await requestProductionPackagePreflight(validPackage, responseFor({
    outcome: "schema-invalid",
    correlationId: parsedPackage.correlationId,
    structurallyValid: null,
    issues: [finding],
  }, 422));
  assert.equal(result.outcome, "schema-invalid");
  assert.equal(result.issues[0]?.path, finding.path);
  assert.equal(result.issues[0]?.message, finding.message);
});

test("structurally invalid packages can return ordered semantic findings with HTTP 200", async () => {
  const result = await requestProductionPackagePreflight(validPackage, responseFor({
    ...successfulResponse(),
    structurallyValid: false,
    issues: [{ path: "audioSegments.0.assetId", code: "asset_reference_missing", message: "The referenced managed asset is not declared in the package." }],
  }));
  assert.equal(result.outcome, "evaluated");
  assert.equal(result.structurallyValid, false);
  assert.equal(result.issues[0]?.code, "asset_reference_missing");
});

test("HTTP request errors display bounded API findings", async () => {
  const result = await requestProductionPackagePreflight(validPackage, responseFor({
    outcome: "request-error",
    correlationId: parsedPackage.correlationId,
    structurallyValid: null,
    issues: [{ path: "", code: "payload_too_large", message: "The request body exceeds the 65536-byte limit." }],
  }, 413));
  assert.equal(result.outcome, "request-error");
  assert.equal(result.issues[0]?.code, "payload_too_large");
});

test("unsupported backend profiles are surfaced as findings", async () => {
  const result = await requestProductionPackagePreflight(validPackage, responseFor({
    outcome: "unsupported",
    correlationId: parsedPackage.correlationId,
    structurallyValid: null,
    issues: [{ path: "rendererProfileId", code: "unsupported_profile", message: "Value does not match the supported production package contract." }],
  }, 422));
  assert.equal(result.outcome, "unsupported");
  assert.equal(result.issues[0]?.code, "unsupported_profile");
});

test("network and server failures do not expose internal details", async () => {
  await assert.rejects(
    requestProductionPackagePreflight(validPackage, async () => { throw new Error("secret provider detail"); }),
    (error: unknown) => isPreflightError(error, "unavailable")
      && !error.message.includes("secret provider detail"),
  );
  await assert.rejects(
    requestProductionPackagePreflight(validPackage, async () => new Response(JSON.stringify({ detail: "secret body" }), { status: 500 })),
    (error: unknown) => isPreflightError(error, "server-error")
      && !error.message.includes("secret body"),
  );
});

test("malformed and inconsistent server responses fail safely", async () => {
  for (const fetcher of [
    async () => new Response("not json", { status: 200 }),
    responseFor({ ...successfulResponse(), correlationId: "00000000-0000-0000-0000-000000000000" }),
    responseFor({ ...successfulResponse(), structurallyValid: false }),
    responseFor({ ...successfulResponse(), issues: [{ path: "secret value", code: "bad", message: "hidden" }] }),
    responseFor({ outcome: "unknown", correlationId: null, structurallyValid: null, issues: [] }),
  ]) {
    await assert.rejects(
      requestProductionPackagePreflight(validPackage, fetcher),
      (error: unknown) => isPreflightError(error, "invalid-response")
        && !error.message.includes("hidden"),
    );
  }
});

test("request client has no persistence or rendering side effects", async () => {
  let calls = 0;
  await requestProductionPackagePreflight(validPackage, async () => {
    calls += 1;
    return new Response(JSON.stringify(successfulResponse()), { status: 200 });
  });
  assert.equal(calls, 1);
  assert.equal("localStorage" in globalThis, false);
});
