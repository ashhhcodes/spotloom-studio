import type {
  ProjectCampaignBrief,
  ProjectCreativeDirection,
  ProjectStoryboardScene,
} from "./projects-api";

export type WorkspaceReadiness = {
  briefComplete: boolean;
  directionConfigured: boolean;
  storyboardPrepared: boolean;
  nextAction: string;
};

export function summarizeWorkspaceReadiness(input: {
  brief: ProjectCampaignBrief;
  direction: ProjectCreativeDirection;
  storyboard: ProjectStoryboardScene[];
}): WorkspaceReadiness {
  const briefComplete = Boolean(
    input.brief.campaign_name.trim()
    && input.brief.brand_name.trim()
    && input.brief.product_or_service.trim()
    && input.brief.target_audience.trim()
    && input.brief.objective
    && input.brief.platform
    && input.brief.call_to_action.trim(),
  );
  const directionConfigured = Boolean(
    input.direction.visual_style.trim()
    || input.direction.advertising_tone.trim()
    || input.direction.primary_message.trim()
    || input.direction.supporting_message.trim()
    || input.direction.audience_emphasis.trim()
    || input.direction.brand_personality.trim()
    || input.direction.desired_video_format
    || input.direction.preferred_duration_seconds,
  );
  const storyboardPrepared = input.storyboard.length > 0
    && input.storyboard.every((scene) => scene.title.trim().length > 0 && scene.status === "ready_for_review");

  return {
    briefComplete,
    directionConfigured,
    storyboardPrepared,
    nextAction: !briefComplete
      ? "Complete the campaign brief."
      : !directionConfigured
        ? "Add a creative direction."
        : !storyboardPrepared
          ? "Prepare the storyboard."
          : "Review the saved creative plan.",
  };
}

export function validateProjectWorkspace(input: {
  brief: ProjectCampaignBrief;
  direction: ProjectCreativeDirection;
  storyboard: ProjectStoryboardScene[];
}): string | null {
  const briefTextLimits: [string, string, number][] = [
    ["campaign_name", input.brief.campaign_name, 120],
    ["brand_name", input.brief.brand_name, 120],
    ["product or service", input.brief.product_or_service, 1000],
    ["target audience", input.brief.target_audience, 500],
    ["call to action", input.brief.call_to_action, 500],
  ];
  if (briefTextLimits.some(([, value, limit]) => value.length > limit)) return "One or more campaign brief fields exceed their supported length.";
  if (input.brief.website_url.length > 2048) return "The website URL exceeds its supported length.";
  if (input.brief.key_selling_points.length > 32 || input.brief.key_selling_points.some((point) => point.length > 500)) {
    return "Use no more than 32 key selling points, with up to 500 characters each.";
  }
  if (Object.values(input.direction).some((value) => typeof value === "string" && value.length > 500)) {
    return "One or more creative direction fields exceed their supported length.";
  }
  const url = input.brief.website_url;
  if (url) {
    try {
      const parsed = new URL(url);
      if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password || /\s|[\u0000-\u001f]/.test(url)) {
        return "Enter a complete HTTP or HTTPS website URL without credentials or whitespace.";
      }
    } catch {
      return "Enter a complete HTTP or HTTPS website URL.";
    }
  }
  if (input.storyboard.length > 32) return "A project storyboard can contain up to 32 scenes.";
  const ids = input.storyboard.map((scene) => scene.id);
  if (ids.some((id) => !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(id)) || new Set(ids).size !== ids.length) return "Each storyboard scene needs a valid, unique ID.";
  if (input.storyboard.some((scene) => !scene.title.trim() || scene.title.length > 120
    || scene.description.length > 500 || scene.visual_direction.length > 1000
    || scene.on_screen_text.length > 500 || scene.narration.length > 1000
    || !Number.isInteger(scene.duration_seconds) || scene.duration_seconds < 1 || scene.duration_seconds > 60
    || !["draft", "ready_for_review"].includes(scene.status))) {
    return "Check scene titles, text limits, status and whole-number duration (1–60 seconds).";
  }
  return null;
}
