import type { Metadata } from "next";
import CreativeReadinessWorkspace from "./creative-readiness-workspace";
import "./creative.css";

export const metadata: Metadata = {
  title: "Creative readiness — Northstar Coffee demo — Spotloom Studio",
  description: "An illustrative readiness overview for the Northstar Coffee sample project.",
};

export default function NorthstarCreativeReadinessPage() {
  return <CreativeReadinessWorkspace />;
}
