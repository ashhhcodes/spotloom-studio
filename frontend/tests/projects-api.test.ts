import assert from "node:assert/strict";
import test from "node:test";

const { createOwnedProject, getOwnedProject, getOwnedProjectCreativeWorkspace, listOwnedProjects, saveOwnedProjectCreativeWorkspace } = await import(
  new URL("../src/app/projects/projects-api.ts", import.meta.url).href
);

function projectRecord(id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") {
  return {
    id,
    name: "Northstar concept",
    created_at: "2026-11-01T12:00:00Z",
    updated_at: "2026-11-01T12:00:00Z",
  };
}

function isProjectError(error: unknown, kind: string): error is Error & { kind: string } {
  return error instanceof Error
    && error.name === "ProjectApiError"
    && (error as Error & { kind?: unknown }).kind === kind;
}

test("listing uses a bearer session token and validates the project list", async () => {
  let url: RequestInfo | URL | undefined;
  let init: RequestInit | undefined;
  const result = await listOwnedProjects(async () => "session-token", async (input: RequestInfo | URL, options?: RequestInit) => {
    url = input;
    init = options;
    return new Response(JSON.stringify([projectRecord()]), { status: 200 });
  });

  assert.equal(url, "/api/adforge/projects");
  assert.equal(init?.method, "GET");
  assert.equal(new Headers(init?.headers).get("authorization"), "Bearer session-token");
  assert.equal(init?.cache, "no-store");
  assert.deepEqual(result, [{
    id: projectRecord().id,
    name: "Northstar concept",
    createdAt: projectRecord().created_at,
    updatedAt: projectRecord().updated_at,
  }]);
});

test("creation sends only a trimmed name, never client ownership or identity", async () => {
  let init: RequestInit | undefined;
  const created = await createOwnedProject("  New campaign  ", async () => "session-token", async (_input: RequestInfo | URL, options?: RequestInit) => {
    init = options;
    return new Response(JSON.stringify(projectRecord()), { status: 201 });
  });

  assert.equal(init?.method, "POST");
  assert.equal(new Headers(init?.headers).get("authorization"), "Bearer session-token");
  assert.deepEqual(JSON.parse(String(init?.body)), { name: "New campaign" });
  assert.deepEqual(created, {
    id: projectRecord().id,
    name: "Northstar concept",
    createdAt: projectRecord().created_at,
    updatedAt: projectRecord().updated_at,
  });
});

test("blank and over-limit names fail before making a request", async () => {
  let calls = 0;
  for (const name of ["  \t ", "x".repeat(121), "😀".repeat(121)]) {
    await assert.rejects(
      createOwnedProject(name, async () => "token", async () => {
        calls += 1;
        return new Response();
      }),
      (error: unknown) => isProjectError(error, "invalid-name"),
    );
  }
  assert.equal(calls, 0);
});

test("missing session token sends no request", async () => {
  let calls = 0;
  await assert.rejects(
    listOwnedProjects(async () => null, async () => {
      calls += 1;
      return new Response();
    }),
    (error: unknown) => isProjectError(error, "missing-token"),
  );
  assert.equal(calls, 0);
});

test("opening a project uses the encoded ID path and validates the response", async () => {
  let url: RequestInfo | URL | undefined;
  const project = await getOwnedProject("project-id/unsafe", async () => "token", async (input: RequestInfo | URL) => {
    url = input;
    return new Response(JSON.stringify(projectRecord("project-id/unsafe")), { status: 200 });
  });
  assert.equal(url, "/api/adforge/projects/project-id%2Funsafe");
  assert.equal(project.id, "project-id/unsafe");
});

test("HTTP, network, and malformed response failures are sanitized", async () => {
  for (const [status, kind] of [[401, "unauthorized"], [404, "not-found"], [422, "invalid-request"], [503, "backend-error"]] as const) {
    await assert.rejects(
      listOwnedProjects(async () => "token", async () => new Response("secret server detail", { status })),
      (error: unknown) => isProjectError(error, kind)
        && !error.message.includes("secret server detail"),
    );
  }
  await assert.rejects(
    listOwnedProjects(async () => "token", async () => { throw new Error("private network detail"); }),
    (error: unknown) => isProjectError(error, "network")
      && !error.message.includes("private network detail"),
  );
  await assert.rejects(
    listOwnedProjects(async () => "token", async () => new Response(JSON.stringify([{ id: "missing-fields" }]), { status: 200 })),
    (error: unknown) => isProjectError(error, "invalid-response"),
  );
});

function workspaceRecord(projectId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") {
  return {
    project_id: projectId,
    revision: 0,
    brief: {
      campaign_name: "", brand_name: "", website_url: "", product_or_service: "",
      target_audience: "", objective: null, platform: null, key_selling_points: [], call_to_action: "",
    },
    creative_direction: {
      visual_style: "", advertising_tone: "", primary_message: "", supporting_message: "",
      audience_emphasis: "", brand_personality: "", desired_video_format: null, preferred_duration_seconds: null,
    },
    storyboard: [],
    created_at: null,
    updated_at: null,
  };
}

test("project creative workspace loads from the owner-scoped same-origin endpoint", async () => {
  let url: RequestInfo | URL | undefined;
  const result = await getOwnedProjectCreativeWorkspace("project-123", async () => "session-token", async (input: RequestInfo | URL) => {
    url = input;
    return new Response(JSON.stringify(workspaceRecord("project-123")), { status: 200 });
  });
  assert.equal(url, "/api/adforge/projects/project-123/creative-workspace");
  assert.equal(result.revision, 0);
  assert.deepEqual(result.storyboard, []);
});

test("workspace save sends only planning data and the expected revision", async () => {
  let init: RequestInit | undefined;
  const body = {
    revision: 0,
    brief: workspaceRecord().brief,
    creative_direction: workspaceRecord().creative_direction,
    storyboard: [{
      id: "scene-opening", title: "Opening", description: "", visual_direction: "",
      on_screen_text: "", narration: "", duration_seconds: 5, status: "draft" as const,
    }],
  };
  const result = await saveOwnedProjectCreativeWorkspace("project-123", body, async () => "session-token", async (_input: RequestInfo | URL, options?: RequestInit) => {
    init = options;
    return new Response(JSON.stringify({ ...workspaceRecord("project-123"), ...body, revision: 1, created_at: "2026-11-11T10:00:00Z", updated_at: "2026-11-11T10:00:00Z" }), { status: 200 });
  });
  assert.equal(init?.method, "PUT");
  assert.equal(new Headers(init?.headers).get("authorization"), "Bearer session-token");
  assert.deepEqual(JSON.parse(String(init?.body)), body);
  assert.equal("owner_user_id" in JSON.parse(String(init?.body)), false);
  assert.equal(result.project_id, "project-123");
  assert.equal(result.revision, 1);
});

test("workspace API rejects a mismatched project response and handles conflicts safely", async () => {
  await assert.rejects(
    getOwnedProjectCreativeWorkspace("expected-project", async () => "token", async () => new Response(JSON.stringify(workspaceRecord("other-project")), { status: 200 })),
    (error: unknown) => isProjectError(error, "invalid-response"),
  );
  await assert.rejects(
    getOwnedProjectCreativeWorkspace("project-123", async () => "token", async () => new Response("internal detail", { status: 409 })),
    (error: unknown) => isProjectError(error, "conflict") && !error.message.includes("internal detail"),
  );
});
