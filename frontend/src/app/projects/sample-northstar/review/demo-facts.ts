export type ReviewStatus = "Unreviewed" | "Approved" | "Rejected";

export type DemoFact = {
  id: string;
  category: string;
  claim: string;
  originalClaim: string;
  revisions: string[];
  status: ReviewStatus;
};

export const initialDemoFacts: DemoFact[] = [
  { id: "product", category: "Product", claim: "Small-batch roasted coffee", originalClaim: "Small-batch roasted coffee", revisions: [], status: "Unreviewed" },
  { id: "audience", category: "Audience", claim: "People looking for a considered everyday cup", originalClaim: "People looking for a considered everyday cup", revisions: [], status: "Approved" },
  { id: "message", category: "Possible message", claim: "A good cup, made simple.", originalClaim: "A good cup, made simple.", revisions: [], status: "Rejected" },
];
