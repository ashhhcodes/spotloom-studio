export type StoryboardScene = {
  id: string;
  title: string;
  narrativePurpose: string;
  visualDirection: string;
  onScreenText: string;
  narration: string;
  durationSeconds: number;
  transition: "cut" | "fade";
  role?: StoryboardSceneRole;
  transitionNote: string;
};

export type StoryboardSceneRole = "hook" | "benefit" | "proof" | "cta";
export type IllustrativeBrandPalette = { primary: string; accent: string };

export const DEFAULT_ILLUSTRATIVE_BRAND_PALETTE: IllustrativeBrandPalette = {
  primary: "#D98B45",
  accent: "#F5EFE7",
};

export const STORYBOARD_FADE_SECONDS = 0.35;
export const MAX_ILLUSTRATIVE_RENDER_SECONDS = 30;

/** A scene duration is valid for planning only when it is a whole second from 1 to 60. */
export function isValidStoryboardDuration(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 60;
}

/** Sum a complete set of valid scene durations; return null when no reliable runtime exists. */
export function calculateStoryboardRuntime(durations: readonly unknown[]): number | null {
  if (durations.length === 0 || !durations.every(isValidStoryboardDuration)) return null;
  return durations.reduce<number>((total, duration) => total + (duration as number), 0);
}

/** Calculate the local illustrative timeline after supported crossfade overlaps. */
export function calculateIllustrativeRenderRuntime(scenes: readonly StoryboardScene[]): number | null {
  const durations = scenes.map((scene) => scene.durationSeconds);
  if (!durations.length || !durations.every(isValidStoryboardDuration)
    || scenes.some((scene, index) => (scene.transition !== "cut" && scene.transition !== "fade")
      || (index === 0 && scene.transition !== "cut"))) return null;
  return durations.reduce<number>((total, duration) => total + duration, 0)
    - scenes.slice(1).filter((scene) => scene.transition === "fade").length * STORYBOARD_FADE_SECONDS;
}

/** Illustrative creative planning only; no footage, narration, or advertisement exists. */
export const initialNorthstarStoryboard: StoryboardScene[] = [
  {
    id: "northstar-scene-opening",
    title: "Set the mood",
    narrativePurpose: "Establish a calm, everyday campaign tone.",
    visualDirection: "A quiet tabletop comes into view. This is a visual suggestion, not captured footage.",
    onScreenText: "A moment to pause",
    narration: "Take a moment.",
    durationSeconds: 4,
    transitionNote: "Fade in, then hold briefly.",
    transition: "cut",
    role: "hook",
  },
  {
    id: "northstar-scene-middle",
    title: "Make room",
    narrativePurpose: "Give the central message space to land.",
    visualDirection: "An illustrative cup sits beside an open notebook; no real product details are shown.",
    onScreenText: "Make space for good.",
    narration: "A little room in the day.",
    durationSeconds: 6,
    transitionNote: "Use a gentle cut between moments.",
    transition: "cut",
    role: "benefit",
  },
  {
    id: "northstar-scene-close",
    title: "Close simply",
    narrativePurpose: "End with a clear, low-pressure next step.",
    visualDirection: "A simple Northstar Coffee demo end card; no logo asset or finished artwork is supplied.",
    onScreenText: "Northstar Coffee · Learn more",
    narration: "Learn more.",
    durationSeconds: 5,
    transitionNote: "Hold the end card, then fade out.",
    transition: "fade",
    role: "cta",
  },
];

export function cloneInitialStoryboard(): StoryboardScene[] {
  return initialNorthstarStoryboard.map((scene) => ({ ...scene }));
}

export function updateStoryboardScene(
  scenes: readonly StoryboardScene[],
  sceneId: string,
  patch: Partial<StoryboardScene>,
): StoryboardScene[] {
  return scenes.map((scene) => scene.id === sceneId ? { ...scene, ...patch, id: scene.id } : scene);
}

export function appendStoryboardScene(
  scenes: readonly StoryboardScene[],
  scene: StoryboardScene,
): StoryboardScene[] {
  return [...scenes, { ...scene }];
}

export function deleteStoryboardScene(scenes: readonly StoryboardScene[], sceneId: string): StoryboardScene[] {
  return scenes.filter((scene) => scene.id !== sceneId);
}

export function moveStoryboardScene(
  scenes: readonly StoryboardScene[],
  sceneId: string,
  direction: -1 | 1,
): StoryboardScene[] {
  const index = scenes.findIndex((scene) => scene.id === sceneId);
  const destination = index + direction;
  if (index < 0 || destination < 0 || destination >= scenes.length) return [...scenes];
  const reordered = [...scenes];
  [reordered[index], reordered[destination]] = [reordered[destination], reordered[index]];
  if (reordered[0].transition !== "cut") reordered[0] = { ...reordered[0], transition: "cut" };
  return reordered;
}
