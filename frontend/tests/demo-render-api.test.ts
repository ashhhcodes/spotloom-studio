import assert from "node:assert/strict";
import test from "node:test";

const { requestDemoRender, toDemoRenderInput } = await import(
  new URL("../src/app/projects/sample-northstar/creative/demo-render-api.ts", import.meta.url).href
);
const { calculateIllustrativeRenderRuntime, cloneInitialStoryboard } = await import(
  new URL("../src/app/projects/sample-northstar/storyboard-model.ts", import.meta.url).href
);

const input = {
  business_name: "Northstar Coffee",
  product_or_service: "Small-batch roasted coffee",
  selling_points: ["A moment to pause", "New scene text", "Learn more"],
  cta: "Learn more",
  primary_color: "#D98B45",
  accent_color: "#F5EFE7",
  scenes: [
    { scene_id: "first", title: "Opening", on_screen_text: " A moment to pause ", duration_seconds: 2, transition: "cut", role: "hook" },
    { scene_id: "added", title: "Added scene", on_screen_text: "New scene text", duration_seconds: 3, transition: "fade", role: "proof" },
    { scene_id: "last", title: "Closing", on_screen_text: "Learn more", duration_seconds: 5, transition: "cut", role: "cta" },
    { scene_id: "fourth", title: "Fourth", on_screen_text: "Fourth copy", duration_seconds: 4, transition: "fade", role: "benefit" },
  ],
};

test("maps every live storyboard scene in order, including newly added scenes", () => {
  assert.deepEqual(toDemoRenderInput({
    businessName: "Northstar Coffee",
    productOrService: "Small-batch roasted coffee",
    storyboardScenes: [
      { id: "first", title: "Opening", onScreenText: " A moment to pause ", durationSeconds: 2, transition: "cut", role: "hook" },
      { id: "added", title: "Added scene", onScreenText: "New scene text", durationSeconds: 3, transition: "fade", role: "proof" },
      { id: "last", title: "Closing", onScreenText: "Learn more", durationSeconds: 5, transition: "cut", role: "cta" },
      { id: "fourth", title: "Fourth", onScreenText: "Fourth copy", durationSeconds: 4, transition: "fade", role: "benefit" },
    ],
    cta: "Learn more",
    brandPalette: { primary: "#D98B45", accent: "#F5EFE7" },
  }), input);
});

test("maps custom brand colors into the render request", () => {
  const mapped = toDemoRenderInput({
    businessName: "Northstar Coffee",
    productOrService: "Small-batch roasted coffee",
    storyboardScenes: [
      { id: "first", title: "Opening", onScreenText: "Hello", durationSeconds: 3, transition: "cut" },
    ],
    cta: "Learn more",
    brandPalette: { primary: "#176B87", accent: "#E8B84D" },
  });
  assert.equal(mapped.primary_color, "#176B87");
  assert.equal(mapped.accent_color, "#E8B84D");
});

test("omits scene role when consuming older storyboard data", () => {
  const mapped = toDemoRenderInput({
    businessName: "Northstar Coffee",
    productOrService: "Small-batch roasted coffee",
    storyboardScenes: [
      { id: "older-scene", title: "Older scene", onScreenText: "Existing copy", durationSeconds: 3, transition: "cut" },
    ],
    cta: "Learn more",
  });
  assert.equal(Object.hasOwn(mapped.scenes[0], "role"), false);
});

test("estimates storyboard runtime from durations and fade overlaps", () => {
  const scenes = cloneInitialStoryboard();
  assert.equal(calculateIllustrativeRenderRuntime(scenes), 14.65);
  scenes[0] = { ...scenes[0], durationSeconds: 6 };
  assert.equal(calculateIllustrativeRenderRuntime(scenes), 16.65);
  scenes[2] = { ...scenes[2], transition: "cut" };
  assert.equal(calculateIllustrativeRenderRuntime(scenes), 17);
});

test("requests one same-origin local render and returns the MP4 blob", async () => {
  let calls = 0;
  let requestUrl: RequestInfo | URL | undefined;
  let requestInit: RequestInit | undefined;
  const video = new Blob([new Uint8Array([0, 0, 0, 0, 102, 116, 121, 112])], { type: "video/mp4" });
  const result = await requestDemoRender(input, async (url: RequestInfo | URL, init?: RequestInit) => {
    calls += 1;
    requestUrl = url;
    requestInit = init;
    return new Response(video, { status: 200, headers: { "content-type": "video/mp4" } });
  });

  assert.equal(calls, 1);
  assert.equal(requestUrl, "/api/adforge/render/demo");
  assert.equal(requestInit?.method, "POST");
  assert.deepEqual(JSON.parse(String(requestInit?.body)), input);
  assert.equal(result.type, "video/mp4");
  assert.equal(result.size, video.size);
});

test("surfaces bounded HTTP and network errors without leaking response bodies", async () => {
  for (const [status, expected] of [
    [422, "whole-second durations"],
    [413, "request limit"],
    [500, "Check FFmpeg and FFprobe"],
  ] as const) {
    await assert.rejects(
      requestDemoRender(input, async () => new Response("secret backend detail", { status })),
      (error: unknown) => error instanceof Error && error.message.includes(expected)
        && !error.message.includes("secret backend detail"),
    );
  }
  await assert.rejects(
    requestDemoRender(input, async () => { throw new Error("private network detail"); }),
    (error: unknown) => error instanceof Error && error.message.includes("unavailable")
      && !error.message.includes("private network detail"),
  );
});

test("rejects unexpected and empty renderer responses", async () => {
  await assert.rejects(
    requestDemoRender(input, async () => new Response("not video", { status: 200, headers: { "content-type": "application/json" } })),
    /unexpected response/,
  );
  await assert.rejects(
    requestDemoRender(input, async () => new Response(new Blob([], { type: "video/mp4" }), { status: 200 })),
    /empty video/,
  );
});
