export type CampaignObjective = "awareness" | "engagement" | "traffic" | "conversions";
export type CampaignPlatform = "instagram" | "tiktok" | "youtube" | "other";
export type BriefAspectRatio = "9:16" | "1:1" | "16:9";
export type BriefDuration = 15 | 30 | 60;

export type CreativeBrief = {
  objective: CampaignObjective;
  targetAudience: string;
  productOrOffer: string;
  keyMessage: string;
  valueProposition: string;
  platform: CampaignPlatform;
  aspectRatio: BriefAspectRatio;
  duration: BriefDuration;
  tone: string;
  callToAction: string;
  reliedUponFactIds: string[];
  /** An explicit human confirmation for this in-memory demo brief; not factual verification. */
  requirementsConfirmed: boolean;
};

/** Illustrative planning defaults only; these are not user-provided campaign requirements. */
export const initialNorthstarBrief: CreativeBrief = {
  objective: "awareness",
  targetAudience: "People looking for a considered everyday cup",
  productOrOffer: "Small-batch roasted coffee",
  keyMessage: "A good cup, made simple.",
  valueProposition: "",
  platform: "instagram",
  aspectRatio: "9:16",
  duration: 15,
  tone: "Warm, considered, and clear",
  callToAction: "Learn more",
  reliedUponFactIds: ["audience", "product", "message"],
  requirementsConfirmed: false,
};
