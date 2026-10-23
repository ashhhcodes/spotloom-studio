import type { Metadata } from "next";
import ProductionPackagePreview from "./production-package-preview";
import "./package.css";

export const metadata: Metadata = {
  title: "Production package preview — Northstar Coffee demo — Spotloom Studio",
  description: "A read-only illustrative review of the current Northstar Coffee brief, storyboard, demo facts, and validation findings.",
};

export default function NorthstarProductionPackagePage() {
  return <ProductionPackagePreview />;
}
