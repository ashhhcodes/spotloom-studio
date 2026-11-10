import assert from "node:assert/strict";
import test from "node:test";

const { summarizeWorkspaceReadiness, validateProjectWorkspace } = await import(
  new URL("../src/app/projects/project-workspace-utils.ts", import.meta.url).href
);

const brief = {
  campaign_name: "", brand_name: "", website_url: "", product_or_service: "",
  target_audience: "", objective: null, platform: null, key_selling_points: [], call_to_action: "",
};
const direction = {
  visual_style: "", advertising_tone: "", primary_message: "", supporting_message: "",
  audience_emphasis: "", brand_personality: "", desired_video_format: null, preferred_duration_seconds: null,
};

test("saved readiness reports actual missing campaign inputs and never invents progress", () => {
  const result = summarizeWorkspaceReadiness({ brief, direction, storyboard: [] });
  assert.deepEqual(result, {
    briefComplete: false,
    directionConfigured: false,
    storyboardPrepared: false,
    nextAction: "Complete the campaign brief.",
  });
});

test("readiness marks the saved storyboard prepared only when all scenes are editorially ready", () => {
  const completeBrief = {
    ...brief,
    campaign_name: "Launch",
    brand_name: "Spotloom",
    product_or_service: "Creative workflow",
    target_audience: "Small teams",
    objective: "awareness" as const,
    platform: "instagram" as const,
    call_to_action: "Learn more",
  };
  const configuredDirection = { ...direction, visual_style: "Editorial" };
  const scene = {
    id: "scene-1", title: "Opening", description: "", visual_direction: "", on_screen_text: "",
    narration: "", duration_seconds: 5, status: "draft" as const,
  };
  assert.equal(summarizeWorkspaceReadiness({ brief: completeBrief, direction: configuredDirection, storyboard: [scene] }).storyboardPrepared, false);
  assert.equal(summarizeWorkspaceReadiness({ brief: completeBrief, direction: configuredDirection, storyboard: [{ ...scene, status: "ready_for_review" }] }).storyboardPrepared, true);
});

test("workspace validation accepts empty drafts and rejects malformed URLs and storyboard bounds", () => {
  assert.equal(validateProjectWorkspace({ brief, direction, storyboard: [] }), null);
  assert.match(String(validateProjectWorkspace({ brief: { ...brief, website_url: "javascript:alert(1)" }, direction, storyboard: [] })), /HTTP or HTTPS/);
  assert.match(String(validateProjectWorkspace({ brief, direction, storyboard: Array.from({ length: 33 }, (_, index) => ({
    id: `scene-${index}`, title: "Scene", description: "", visual_direction: "", on_screen_text: "",
    narration: "", duration_seconds: 5, status: "draft" as const,
  })) })), /up to 32 scenes/);
  assert.match(String(validateProjectWorkspace({ brief, direction, storyboard: [{
    id: "scene-1", title: "Scene", description: "", visual_direction: "", on_screen_text: "",
    narration: "", duration_seconds: 61, status: "draft",
  }] })), /duration/);
});
