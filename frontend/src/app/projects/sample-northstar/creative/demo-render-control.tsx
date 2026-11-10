"use client";

import { useEffect, useRef, useState } from "react";
import { DemoRenderError, requestDemoRender, type DemoRenderInput } from "./demo-render-api";

type RenderState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; url: string };

export default function DemoRenderControl({ input }: { input: DemoRenderInput }) {
  const [render, setRender] = useState<RenderState>({ status: "idle" });
  const active = useRef(false);
  const objectUrl = useRef<string | null>(null);

  useEffect(() => () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  async function generate() {
    if (active.current) return;
    active.current = true;
    if (objectUrl.current) {
      URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    }
    setRender({ status: "loading" });
    try {
      const video = await requestDemoRender(input);
      const url = URL.createObjectURL(video);
      objectUrl.current = url;
      setRender({ status: "success", url });
    } catch (error) {
      const message = error instanceof DemoRenderError
        ? error.message
        : "The local demo renderer could not complete this request.";
      setRender({ status: "error", message });
    } finally {
      active.current = false;
    }
  }

  return (
    <div className="readiness-next-actions" aria-busy={render.status === "loading"}>
      <button type="button" onClick={generate} disabled={render.status === "loading"}>
        {render.status === "loading" ? "Rendering local draft…" : "Generate Ad"}
        <span aria-hidden="true">↗</span>
      </button>
      <p role={render.status === "error" ? "alert" : "status"} aria-live={render.status === "error" ? "assertive" : "polite"}>
        {render.status === "idle" && "Creates a temporary illustrative MP4 with the existing local renderer; it is not a production-ready ad."}
        {render.status === "loading" && "Rendering a short video locally. The output is streamed back and is not saved as a project asset."}
        {render.status === "error" && render.message}
        {render.status === "success" && "Illustrative video draft generated. It has no audio and does not verify claims or assets."}
      </p>
      {render.status === "success" && (
        <div className="demo-render-result">
          <video controls preload="metadata" src={render.url} aria-label="Illustrative local video draft" />
          <a href={render.url} download="spotloom-illustrative-draft.mp4">Download illustrative MP4</a>
        </div>
      )}
    </div>
  );
}
