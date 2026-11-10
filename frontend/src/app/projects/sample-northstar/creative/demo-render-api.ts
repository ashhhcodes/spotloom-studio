export type DemoRenderInput = {
  business_name: string;
  product_or_service: string;
  selling_points: string[];
  cta: string;
  primary_color: string;
  accent_color: string;
  scenes: DemoRenderScene[];
};

export type DemoRenderScene = {
  scene_id: string;
  title: string;
  on_screen_text: string;
  duration_seconds: number;
  transition: "cut" | "fade";
  role?: "hook" | "benefit" | "proof" | "cta";
};

export type DemoRenderSource = {
  businessName: string;
  productOrService: string;
  storyboardScenes: readonly {
    id: string;
    title: string;
    onScreenText: string;
    durationSeconds: number;
    transition: "cut" | "fade";
    role?: "hook" | "benefit" | "proof" | "cta";
  }[];
  cta: string;
  brandPalette?: { primary: string; accent: string };
};

const defaultBrandPalette = { primary: "#D98B45", accent: "#F5EFE7" } as const;

export class DemoRenderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DemoRenderError";
  }
}

const endpoint = "/api/adforge/render/demo";

export function toDemoRenderInput(source: DemoRenderSource): DemoRenderInput {
  return {
    business_name: source.businessName,
    product_or_service: source.productOrService,
    selling_points: source.storyboardScenes.map((scene) => scene.onScreenText.trim()).filter(Boolean).slice(0, 3),
    cta: source.cta,
    primary_color: source.brandPalette?.primary ?? defaultBrandPalette.primary,
    accent_color: source.brandPalette?.accent ?? defaultBrandPalette.accent,
    scenes: source.storyboardScenes.map((scene) => ({
      scene_id: scene.id,
      title: scene.title,
      on_screen_text: scene.onScreenText,
      duration_seconds: scene.durationSeconds,
      transition: scene.transition,
      ...(scene.role ? { role: scene.role } : {}),
    })),
  };
}

export async function requestDemoRender(input: DemoRenderInput, fetcher: typeof fetch = fetch): Promise<Blob> {
  let response: Response;
  try {
    response = await fetcher(endpoint, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    throw new DemoRenderError("The local demo renderer is unavailable. Start the backend and retry.");
  }

  if (!response.ok) {
    if (response.status === 422) {
      throw new DemoRenderError("Use 1–6 unique scenes with non-blank titles and on-screen text, supported roles (hook, benefit, proof, cta), whole-second durations from 1–60, cut or fade transitions, a cut first scene, and a rendered timeline no longer than 30 seconds.");
    }
    if (response.status === 413) {
      throw new DemoRenderError("The current workspace text exceeds the local render request limit.");
    }
    if (response.status >= 500) {
      throw new DemoRenderError("The local renderer could not generate the video. Check FFmpeg and FFprobe, then retry.");
    }
    throw new DemoRenderError("The local renderer rejected this request.");
  }

  if (!response.headers.get("content-type")?.toLowerCase().startsWith("video/mp4")) {
    throw new DemoRenderError("The local renderer returned an unexpected response instead of an MP4 video.");
  }

  let video: Blob;
  try {
    video = await response.blob();
  } catch {
    throw new DemoRenderError("The generated video response could not be read. Retry the render.");
  }
  if (video.size === 0) {
    throw new DemoRenderError("The renderer returned an empty video. Retry the render.");
  }
  return video;
}
