import assert from "node:assert/strict";
import test from "node:test";

const { verifyBackendIdentity } = await import(
  new URL("../src/app/auth/identity-api.ts", import.meta.url).href
);

function isIdentityError(error: unknown, kind: string): error is Error & { kind: string } {
  return error instanceof Error
    && error.name === "IdentityCheckError"
    && (error as Error & { kind?: unknown }).kind === kind;
}

test("session token is requested in memory and sent to the same-origin protected endpoint", async () => {
  let calls = 0;
  let requestUrl: RequestInfo | URL | undefined;
  let requestInit: RequestInit | undefined;
  const identity = await verifyBackendIdentity(
    async () => "short-lived-test-session-token",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      calls += 1;
      requestUrl = input;
      requestInit = init;
      return new Response(JSON.stringify({
        authenticated: true,
        principal: { issuer: "https://clerk.example", subject: "user_test" },
      }), { status: 200 });
    },
  );

  assert.equal(calls, 1);
  assert.equal(requestUrl, "/api/adforge/auth/identity");
  assert.equal(requestInit?.method, "GET");
  assert.equal(new Headers(requestInit?.headers).get("authorization"), "Bearer short-lived-test-session-token");
  assert.equal(requestInit?.cache, "no-store");
  assert.equal(requestInit?.redirect, "error");
  assert.deepEqual(identity, { issuer: "https://clerk.example", subject: "user_test" });
});

test("missing session token fails without sending a request", async () => {
  let calls = 0;
  await assert.rejects(
    verifyBackendIdentity(async () => null, async () => {
      calls += 1;
      return new Response();
    }),
    (error: unknown) => isIdentityError(error, "missing-token"),
  );
  assert.equal(calls, 0);
});

test("token retrieval and network failures return sanitized errors", async () => {
  await assert.rejects(
    verifyBackendIdentity(async () => { throw new Error("private token detail"); }),
    (error: unknown) => isIdentityError(error, "token-unavailable")
      && !error.message.includes("private token detail"),
  );
  await assert.rejects(
    verifyBackendIdentity(async () => "test-token", async () => { throw new Error("private proxy detail"); }),
    (error: unknown) => isIdentityError(error, "network")
      && !error.message.includes("private proxy detail"),
  );
});

test("backend authentication and configuration errors are clear and sanitized", async () => {
  for (const [status, kind] of [[401, "unauthorized"], [503, "backend-not-configured"], [500, "backend-error"]] as const) {
    await assert.rejects(
      verifyBackendIdentity(async () => "test-token", async () => new Response("private server detail", { status })),
      (error: unknown) => isIdentityError(error, kind)
        && !error.message.includes("private server detail"),
    );
  }
});

test("unexpected identity responses fail safely", async () => {
  for (const body of ["not json", JSON.stringify({ authenticated: true, principal: { subject: "missing issuer" } })]) {
    await assert.rejects(
      verifyBackendIdentity(async () => "test-token", async () => new Response(body, { status: 200 })),
      (error: unknown) => isIdentityError(error, "invalid-response"),
    );
  }
});
