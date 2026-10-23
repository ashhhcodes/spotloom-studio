import type { Metadata } from "next";
import StoryboardWorkspace from "./storyboard-workspace";
import "./storyboard.css";

export const metadata: Metadata = {
  title: "Storyboard — Northstar Coffee demo — Spotloom Studio",
  description: "An illustrative, in-memory storyboard for the Northstar Coffee sample project.",
};

export default function NorthstarStoryboardPage() {
  return <StoryboardWorkspace />;
}
