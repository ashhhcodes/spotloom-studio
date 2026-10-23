import type { ReactNode } from "react";
import { NorthstarDemoProjectProvider } from "./demo-project-provider";

export default function NorthstarProjectLayout({ children }: { children: ReactNode }) {
  return <NorthstarDemoProjectProvider>{children}</NorthstarDemoProjectProvider>;
}
