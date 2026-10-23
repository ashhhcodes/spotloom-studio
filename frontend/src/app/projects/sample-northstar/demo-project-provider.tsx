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

type NorthstarProjectState = {
  facts: ProjectFact[];
  brief: CreativeBrief;
  decideFact: (factId: string, decision: ReviewDecision) => void;
  correctFact: (factId: string, correctedClaim: string) => void;
  updateBrief: (patch: Partial<CreativeBrief>) => void;
  resetBrief: () => void;
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

  const value = useMemo<NorthstarProjectState>(() => ({
    facts,
    brief,
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
  }), [facts, brief]);

  return <NorthstarProjectContext.Provider value={value}>{children}</NorthstarProjectContext.Provider>;
}

export function useNorthstarProjectState() {
  const value = useContext(NorthstarProjectContext);
  if (!value) {
    throw new Error("Northstar project state must be used inside NorthstarDemoProjectProvider.");
  }
  return value;
}
