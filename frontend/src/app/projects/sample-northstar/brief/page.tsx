import type { Metadata } from "next";
import CreativeBriefWorkspace from "./creative-brief-workspace";
import "./brief.css";

export const metadata: Metadata = {
  title: "Creative brief — Northstar Coffee demo — Spotloom Studio",
  description: "An illustrative, in-memory creative brief for the Northstar Coffee sample project.",
};

export default function NorthstarCreativeBriefPage() {
  return <CreativeBriefWorkspace />;
}
