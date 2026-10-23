"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import {
  correctDemoFact,
  decideDemoFact,
  northstarDemoProject,
  type ProjectFact,
  type ReviewDecision,
} from "./review/demo-facts";

type NorthstarProjectState = {
  facts: ProjectFact[];
  decideFact: (factId: string, decision: ReviewDecision) => void;
  correctFact: (factId: string, correctedClaim: string) => void;
};

const NorthstarProjectContext = createContext<NorthstarProjectState | null>(null);

export function NorthstarDemoProjectProvider({ children }: { children: ReactNode }) {
  const [facts, setFacts] = useState<ProjectFact[]>(() => northstarDemoProject.facts.map((fact) => ({
    ...fact,
    revisions: [...fact.revisions],
    source: { ...fact.source },
  })));

  const value = useMemo<NorthstarProjectState>(() => ({
    facts,
    decideFact: (factId, decision) => setFacts((current) => current.map((fact) =>
      fact.id === factId ? decideDemoFact(fact, decision) : fact,
    )),
    correctFact: (factId, correctedClaim) => setFacts((current) => current.map((fact) =>
      fact.id === factId ? correctDemoFact(fact, correctedClaim) : fact,
    )),
  }), [facts]);

  return <NorthstarProjectContext.Provider value={value}>{children}</NorthstarProjectContext.Provider>;
}

export function useNorthstarProjectState() {
  const value = useContext(NorthstarProjectContext);
  if (!value) {
    throw new Error("Northstar project state must be used inside NorthstarDemoProjectProvider.");
  }
  return value;
}
