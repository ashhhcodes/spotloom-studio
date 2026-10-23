export type ReviewStatus = "unreviewed" | "approved" | "rejected";

export type DemoFactSource = {
  kind: "illustrative-placeholder";
  reference: string;
  pageOrSection: string;
  excerpt: string | null;
};

export type ProjectFact = {
  id: string;
  category: string;
  claim: string;
  originalClaim: string;
  revisions: string[];
  status: ReviewStatus;
  source: DemoFactSource;
};

export type DemoProject = {
  id: string;
  name: string;
  isIllustrative: true;
  facts: ProjectFact[];
};

const noWebsiteSource: DemoFactSource = {
  kind: "illustrative-placeholder",
  reference: "Demo source — no website scanned",
  pageOrSection: "Placeholder — no page inspected",
  excerpt: null,
};

export const northstarDemoProject: DemoProject = {
  id: "sample-northstar",
  name: "Northstar Coffee",
  isIllustrative: true,
  facts: [
    { id: "product", category: "Product", claim: "Small-batch roasted coffee", originalClaim: "Small-batch roasted coffee", revisions: [], status: "unreviewed", source: noWebsiteSource },
    { id: "audience", category: "Audience", claim: "People looking for a considered everyday cup", originalClaim: "People looking for a considered everyday cup", revisions: [], status: "approved", source: noWebsiteSource },
    { id: "message", category: "Possible message", claim: "A good cup, made simple.", originalClaim: "A good cup, made simple.", revisions: [], status: "rejected", source: noWebsiteSource },
  ],
};

export type ReviewStatusCounts = Record<ReviewStatus, number>;

export function deriveReviewStatusCounts(facts: readonly ProjectFact[]): ReviewStatusCounts {
  return facts.reduce<ReviewStatusCounts>(
    (counts, fact) => ({ ...counts, [fact.status]: counts[fact.status] + 1 }),
    { unreviewed: 0, approved: 0, rejected: 0 },
  );
}

/** Approved for this illustrative demo only; this does not establish real-world verification. */
export function getApprovedDemoFacts(facts: readonly ProjectFact[]): ProjectFact[] {
  return facts.filter((fact) => fact.status === "approved");
}

/** Apply an in-memory correction, retaining prior wording and requiring a fresh review. */
export function correctDemoFact(fact: ProjectFact, correctedClaim: string): ProjectFact {
  const claim = correctedClaim.trim();
  if (!claim) {
    throw new Error("A corrected claim cannot be empty.");
  }

  return {
    ...fact,
    claim,
    revisions: [...fact.revisions, fact.claim],
    status: "unreviewed",
  };
}
