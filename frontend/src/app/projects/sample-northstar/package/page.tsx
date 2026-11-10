import type { Metadata } from "next";
import ProductionPackagePreview from "./production-package-preview";
import "./package.css";

export const metadata: Metadata = {
  title: "Production package preview — Northstar Coffee demo — Spotloom Studio",
  description: "Review the illustrative Northstar Coffee plan and explicitly preflight a v2 package's structure in the local demo.",
};

export default function NorthstarProductionPackagePage() {
  return <ProductionPackagePreview />;
}
