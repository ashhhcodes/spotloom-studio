"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import {
  correctDemoFact,
  decideDemoFact,
  northstarDemoProject,
  type ProjectFact,
  type ReviewDecision,
} from "./review/demo-facts";
import { initialNorthstarBrief, type CreativeBrief } from "./creative-brief";
import { cloneInitialStoryboard, type StoryboardScene } from "./storyboard-model";

type NorthstarProjectState = {
  facts: ProjectFact[];
  brief: CreativeBrief;
  scenes: StoryboardScene[];
  decideFact: (factId: string, decision: ReviewDecision) => void;
  correctFact: (factId: string, correctedClaim: string) => void;
  updateBrief: (patch: Partial<CreativeBrief>) => void;
  resetBrief: () => void;
  updateScene: (sceneId: string, patch: Partial<StoryboardScene>) => void;
  addScene: () => void;
  deleteScene: (sceneId: string) => void;
  moveScene: (sceneId: string, direction: -1 | 1) => void;
  resetStoryboard: () => void;
};

function cloneInitialBrief(): CreativeBrief {
  return { ...initialNorthstarBrief, reliedUponFactIds: [...initialNorthstarBrief.reliedUponFactIds] };
}

const NorthstarProjectContext = createContext<NorthstarProjectState | null>(null);

export function NorthstarDemoProjectProvider({ children }: { children: ReactNode }) {
  const [facts, setFacts] = useState<ProjectFact[]>(() => northstarDemoProject.facts.map((fact) => ({
    ...fact,
    revisions: [...fact.revisions],
    source: { ...fact.source },
  })));
  const [brief, setBrief] = useState<CreativeBrief>(cloneInitialBrief);
  const [scenes, setScenes] = useState<StoryboardScene[]>(cloneInitialStoryboard);

  const value = useMemo<NorthstarProjectState>(() => ({
    facts,
    brief,
    scenes,
    decideFact: (factId, decision) => setFacts((current) => current.map((fact) =>
      fact.id === factId ? decideDemoFact(fact, decision) : fact,
    )),
    correctFact: (factId, correctedClaim) => setFacts((current) => current.map((fact) =>
      fact.id === factId ? correctDemoFact(fact, correctedClaim) : fact,
    )),
    updateBrief: (patch) => setBrief((current) => ({ ...current, ...patch,
      reliedUponFactIds: patch.reliedUponFactIds ? [...patch.reliedUponFactIds] : current.reliedUponFactIds,
    })),
    resetBrief: () => setBrief(cloneInitialBrief()),
    updateScene: (sceneId, patch) => setScenes((current) => current.map((scene) =>
      scene.id === sceneId ? { ...scene, ...patch, id: scene.id } : scene,
    )),
    addScene: () => {
      const scene: StoryboardScene = {
        id: crypto.randomUUID(),
        title: "New illustrative scene",
        narrativePurpose: "",
        visualDirection: "",
        onScreenText: "",
        narration: "",
        durationSeconds: 5,
        transitionNote: "",
      };
      setScenes((current) => [...current, scene]);
    },
    deleteScene: (sceneId) => setScenes((current) => current.filter((scene) => scene.id !== sceneId)),
    moveScene: (sceneId, direction) => setScenes((current) => {
      const index = current.findIndex((scene) => scene.id === sceneId);
      const destination = index + direction;
      if (index < 0 || destination < 0 || destination >= current.length) return current;
      const reordered = [...current];
      [reordered[index], reordered[destination]] = [reordered[destination], reordered[index]];
      return reordered;
    }),
    resetStoryboard: () => setScenes(cloneInitialStoryboard()),
  }), [facts, brief, scenes]);

  return <NorthstarProjectContext.Provider value={value}>{children}</NorthstarProjectContext.Provider>;
}

export function useNorthstarProjectState() {
  const value = useContext(NorthstarProjectContext);
  if (!value) {
    throw new Error("Northstar project state must be used inside NorthstarDemoProjectProvider.");
  }
  return value;
}
