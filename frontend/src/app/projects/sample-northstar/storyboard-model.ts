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
