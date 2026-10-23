import { WorkspaceStart } from "@/components/workspace-start";
import "./workspace.css";

export default function Home() {
  return (
    <div className="workspace">
      <section className="workspace-heading" id="overview" aria-labelledby="page-title">
        <div><p className="workspace-kicker">A calmer way to make campaign work</p><h1 id="page-title">Good ideas start with <em>good context.</em></h1><p>Shape a clear picture of the business first. Then decide what deserves to be said.</p></div>
        <span className="workspace-index">WORKSPACE / 01</span>
      </section>
      <WorkspaceStart />
    </div>
  );
}
