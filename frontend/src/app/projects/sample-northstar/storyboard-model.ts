export type StoryboardScene = {
  id: string;
  title: string;
  narrativePurpose: string;
  visualDirection: string;
  onScreenText: string;
  narration: string;
  durationSeconds: number;
  transitionNote: string;
};

/** A scene duration is valid for planning only when it is a whole second from 1 to 60. */
export function isValidStoryboardDuration(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 60;
}

/** Sum a complete set of valid scene durations; return null when no reliable runtime exists. */
export function calculateStoryboardRuntime(durations: readonly unknown[]): number | null {
  if (durations.length === 0 || !durations.every(isValidStoryboardDuration)) return null;
  return durations.reduce<number>((total, duration) => total + (duration as number), 0);
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
  return reordered;
}
