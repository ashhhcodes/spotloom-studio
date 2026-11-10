"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import {
  getOwnedProjectCreativeWorkspace,
  ProjectApiError,
  saveOwnedProjectCreativeWorkspace,
  type ProjectCampaignBrief,
  type ProjectCreativeDirection,
  type ProjectCreativeWorkspace,
  type ProjectStoryboardScene,
} from "./projects-api";
import { summarizeWorkspaceReadiness, validateProjectWorkspace } from "./project-workspace-utils";

type WorkspaceDraft = Pick<ProjectCreativeWorkspace, "revision" | "brief" | "creative_direction" | "storyboard">;

function toDraft(workspace: ProjectCreativeWorkspace): WorkspaceDraft {
  return {
    revision: workspace.revision,
    brief: { ...workspace.brief, key_selling_points: [...workspace.brief.key_selling_points] },
    creative_direction: { ...workspace.creative_direction },
    storyboard: workspace.storyboard.map((scene) => ({ ...scene })),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof ProjectApiError
    ? error.message
    : "The saved creative workspace could not be loaded. Try again.";
}

export function ProjectCreativeWorkspaceEditor({ projectId }: { projectId: string }) {
  const { getToken } = useAuth();
  const getSessionToken = useCallback(() => getToken(), [getToken]);
  const [saved, setSaved] = useState<ProjectCreativeWorkspace | null>(null);
  const [draft, setDraft] = useState<WorkspaceDraft | null>(null);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [hasRevisionConflict, setHasRevisionConflict] = useState(false);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    setHasRevisionConflict(false);
    setNotice("");
    try {
      const result = await getOwnedProjectCreativeWorkspace(projectId, getSessionToken);
      setSaved(result);
      setDraft(toDraft(result));
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [getSessionToken, projectId]);

  useEffect(() => {
    let active = true;
    void getOwnedProjectCreativeWorkspace(projectId, getSessionToken).then((result) => {
      if (active) {
        setSaved(result);
        setDraft(toDraft(result));
      }
    }).catch((error: unknown) => {
      if (active) setLoadError(errorMessage(error));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [getSessionToken, projectId]);

  function updateBrief<K extends keyof ProjectCampaignBrief>(key: K, value: ProjectCampaignBrief[K]) {
    setDraft((current) => current ? { ...current, brief: { ...current.brief, [key]: value } } : current);
    setNotice("");
    setSaveError("");
    setHasRevisionConflict(false);
  }

  function updateDirection<K extends keyof ProjectCreativeDirection>(key: K, value: ProjectCreativeDirection[K]) {
    setDraft((current) => current ? { ...current, creative_direction: { ...current.creative_direction, [key]: value } } : current);
    setNotice("");
    setSaveError("");
    setHasRevisionConflict(false);
  }

  function updateScene(sceneId: string, patch: Partial<ProjectStoryboardScene>) {
    setDraft((current) => current ? {
      ...current,
      storyboard: current.storyboard.map((scene) => scene.id === sceneId ? { ...scene, ...patch } : scene),
    } : current);
    setNotice("");
    setSaveError("");
    setHasRevisionConflict(false);
  }

  function moveScene(index: number, direction: -1 | 1) {
    setDraft((current) => {
      if (!current) return current;
      const destination = index + direction;
      if (destination < 0 || destination >= current.storyboard.length) return current;
      const storyboard = [...current.storyboard];
      [storyboard[index], storyboard[destination]] = [storyboard[destination], storyboard[index]];
      return { ...current, storyboard };
    });
    setNotice("");
    setSaveError("");
    setHasRevisionConflict(false);
  }

  function addScene() {
    const id = `scene-${globalThis.crypto.randomUUID()}`;
    setDraft((current) => current && current.storyboard.length < 32 ? {
      ...current,
      storyboard: [...current.storyboard, {
        id, title: "New scene", description: "", visual_direction: "", on_screen_text: "",
        narration: "", duration_seconds: 5, status: "draft",
      }],
    } : current);
    setNotice("");
    setSaveError("");
    setHasRevisionConflict(false);
  }

  function removeScene(sceneId: string) {
    setDraft((current) => current ? {
      ...current,
      storyboard: current.storyboard.filter((scene) => scene.id !== sceneId),
    } : current);
    setNotice("");
    setSaveError("");
    setHasRevisionConflict(false);
  }

  async function saveWorkspace() {
    if (!draft) return;
    const validationError = validateProjectWorkspace({
      brief: draft.brief,
      direction: draft.creative_direction,
      storyboard: draft.storyboard,
    });
    if (validationError) {
      setSaveError(validationError);
      return;
    }
    setSaving(true);
    setSaveError("");
    setHasRevisionConflict(false);
    setNotice("");
    try {
      const result = await saveOwnedProjectCreativeWorkspace(projectId, draft, getSessionToken);
      setSaved(result);
      setDraft(toDraft(result));
      setNotice("Creative workspace saved to this project.");
    } catch (error) {
      setHasRevisionConflict(error instanceof ProjectApiError && error.kind === "conflict");
      setSaveError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="projects-status" role="status">Loading this project’s creative workspace…</p>;
  if (loadError || !draft || !saved) {
    return <section className="creative-workspace-panel" aria-labelledby="creative-workspace-title">
      <h2 id="creative-workspace-title">Project creative workspace</h2>
      <p className="projects-message projects-message-error" role="alert">{loadError || "The project workspace could not be loaded."}</p>
      <button className="projects-secondary-action" type="button" onClick={() => void loadWorkspace()}>Retry</button>
    </section>;
  }

  const readiness = summarizeWorkspaceReadiness({
    brief: saved.brief,
    direction: saved.creative_direction,
    storyboard: saved.storyboard,
  });
  const isDirty = JSON.stringify(draft) !== JSON.stringify(toDraft(saved));
  const pointText = draft.brief.key_selling_points.join("\n");

  return <div className="creative-workspace-stack">
    <section className="creative-overview" aria-labelledby="creative-overview-title">
      <div className="creative-overview-heading">
        <div><p className="workspace-label">Saved creative plan</p><h2 id="creative-overview-title">A campaign workspace, specific to this project.</h2></div>
        <span className="creative-revision">{saved.revision === 0 ? "Not saved yet" : `Revision ${saved.revision}`}</span>
      </div>
      <p className="creative-campaign-status"><strong>Campaign status</strong>{saved.revision === 0 ? "Not started" : readiness.briefComplete ? "Brief ready for planning" : "Planning in progress"}</p>
      <p className="creative-next-action"><strong>Next action</strong>{readiness.nextAction}</p>
      <ul className="creative-readiness-list" aria-label="Saved creative readiness">
        <ReadinessItem complete={readiness.briefComplete} label="Campaign brief" detail={readiness.briefComplete ? "Required campaign details are saved." : "Campaign name, brand, offer, audience, objective, platform and CTA are still needed."} />
        <ReadinessItem complete={readiness.directionConfigured} label="Creative direction" detail={readiness.directionConfigured ? "User-authored direction is saved." : "No creative direction saved yet."} />
        <ReadinessItem complete={readiness.storyboardPrepared} label="Storyboard" detail={readiness.storyboardPrepared ? `${saved.storyboard.length} saved scenes marked ready for review.` : saved.storyboard.length ? "Mark each saved scene ready for review when the outline is prepared." : "No saved storyboard scenes yet."} />
        <ReadinessItem complete={false} label="Creative assets" detail="Upload, validation and project asset storage are not connected to this workspace." />
      </ul>
      <div className="creative-capability-note">
        <p><strong>Rendering</strong> Project-scoped video rendering is not connected. No video has been created from this project.</p>
        <p><strong>Recent activity</strong> Activity history is not available for project workspaces.</p>
      </div>
      {saved.updated_at && <p className="creative-saved-time">Last saved {formatTimestamp(saved.updated_at)}</p>}
    </section>

    <section className="creative-editor-panel" aria-labelledby="creative-workspace-title">
      <div className="creative-editor-heading"><div><p className="workspace-label">Campaign planning</p><h2 id="creative-workspace-title">Brief &amp; creative direction</h2><p>Draft information is saved only when you choose Save workspace.</p></div></div>

      <fieldset className="creative-fieldset" disabled={saving}>
        <legend>Campaign brief</legend>
        <div className="creative-form-grid">
          <TextField id="campaign-name" label="Campaign name" value={draft.brief.campaign_name} maxLength={120} onChange={(value) => updateBrief("campaign_name", value)} />
          <TextField id="brand-name" label="Brand name" value={draft.brief.brand_name} maxLength={120} onChange={(value) => updateBrief("brand_name", value)} />
          <TextField id="website-url" label="Website URL (optional)" value={draft.brief.website_url} maxLength={2048} onChange={(value) => updateBrief("website_url", value)} type="url" />
          <label className="creative-field creative-field-wide" htmlFor="product-description">Product or service
            <textarea id="product-description" rows={3} maxLength={1000} value={draft.brief.product_or_service} onChange={(event) => updateBrief("product_or_service", event.currentTarget.value)} />
          </label>
          <label className="creative-field creative-field-wide" htmlFor="target-audience">Target audience
            <textarea id="target-audience" rows={2} maxLength={500} value={draft.brief.target_audience} onChange={(event) => updateBrief("target_audience", event.currentTarget.value)} />
          </label>
          <SelectField id="campaign-objective" label="Campaign objective" value={draft.brief.objective ?? ""} options={[["", "Choose objective"], ["awareness", "Awareness"], ["engagement", "Engagement"], ["traffic", "Traffic"], ["conversions", "Conversions"]]} onChange={(value) => updateBrief("objective", value ? value as NonNullable<ProjectCampaignBrief["objective"]> : null)} />
          <SelectField id="campaign-platform" label="Preferred platform" value={draft.brief.platform ?? ""} options={[["", "Choose platform"], ["instagram", "Instagram"], ["tiktok", "TikTok"], ["youtube", "YouTube"], ["other", "Other"]]} onChange={(value) => updateBrief("platform", value ? value as NonNullable<ProjectCampaignBrief["platform"]> : null)} />
          <TextField id="call-to-action" label="Call to action" value={draft.brief.call_to_action} maxLength={500} onChange={(value) => updateBrief("call_to_action", value)} />
          <label className="creative-field creative-field-wide" htmlFor="selling-points">Key selling points <span>One per line, optional</span>
            <textarea id="selling-points" rows={3} maxLength={16032} value={pointText} onChange={(event) => updateBrief("key_selling_points", event.currentTarget.value.split("\n"))} />
          </label>
        </div>
      </fieldset>

      <fieldset className="creative-fieldset" disabled={saving}>
        <legend>Creative direction</legend>
        <div className="creative-form-grid">
          <TextField id="visual-style" label="Visual style" value={draft.creative_direction.visual_style} maxLength={500} onChange={(value) => updateDirection("visual_style", value)} />
          <TextField id="advertising-tone" label="Tone of voice" value={draft.creative_direction.advertising_tone} maxLength={500} onChange={(value) => updateDirection("advertising_tone", value)} />
          <TextField id="primary-message" label="Primary message" value={draft.creative_direction.primary_message} maxLength={500} onChange={(value) => updateDirection("primary_message", value)} />
          <TextField id="supporting-message" label="Supporting message" value={draft.creative_direction.supporting_message} maxLength={500} onChange={(value) => updateDirection("supporting_message", value)} />
          <TextField id="audience-emphasis" label="Audience emphasis" value={draft.creative_direction.audience_emphasis} maxLength={500} onChange={(value) => updateDirection("audience_emphasis", value)} />
          <TextField id="brand-personality" label="Brand personality" value={draft.creative_direction.brand_personality} maxLength={500} onChange={(value) => updateDirection("brand_personality", value)} />
          <SelectField id="video-format" label="Desired format" value={draft.creative_direction.desired_video_format ?? ""} options={[["", "Choose format"], ["9:16", "Vertical · 9:16"], ["1:1", "Square · 1:1"], ["16:9", "Landscape · 16:9"]]} onChange={(value) => updateDirection("desired_video_format", value ? value as NonNullable<ProjectCreativeDirection["desired_video_format"]> : null)} />
          <SelectField id="preferred-duration" label="Preferred duration" value={draft.creative_direction.preferred_duration_seconds?.toString() ?? ""} options={[["", "Choose duration"], ["15", "15 seconds"], ["30", "30 seconds"], ["60", "60 seconds"]]} onChange={(value) => updateDirection("preferred_duration_seconds", value ? Number(value) as 15 | 30 | 60 : null)} />
        </div>
      </fieldset>

      <fieldset className="creative-fieldset" disabled={saving}>
        <legend>Storyboard <span className="creative-legend-note">{draft.storyboard.length} / 32 scenes</span></legend>
        {draft.storyboard.length === 0 ? <p className="creative-empty">No scenes have been saved. Add a scene to begin a project-specific outline.</p> : (
          <ol className="project-scene-list">
            {draft.storyboard.map((scene, index) => <li className="project-scene" key={scene.id}>
              <div className="project-scene-topline"><span>SCENE {String(index + 1).padStart(2, "0")}</span><div>
                <button type="button" className="projects-secondary-action" onClick={() => moveScene(index, -1)} disabled={index === 0} aria-label={`Move scene ${index + 1} up`}>↑</button>
                <button type="button" className="projects-secondary-action" onClick={() => moveScene(index, 1)} disabled={index === draft.storyboard.length - 1} aria-label={`Move scene ${index + 1} down`}>↓</button>
                <button type="button" className="projects-text-action" onClick={() => removeScene(scene.id)} aria-label={`Remove scene ${index + 1}`}>Remove</button>
              </div></div>
              <div className="creative-form-grid">
                <TextField id={`scene-title-${scene.id}`} label="Scene title" value={scene.title} maxLength={120} onChange={(value) => updateScene(scene.id, { title: value })} />
                <label className="creative-field" htmlFor={`scene-duration-${scene.id}`}>Duration (seconds)
                  <input id={`scene-duration-${scene.id}`} type="number" min={1} max={60} step={1} value={scene.duration_seconds} onChange={(event) => updateScene(scene.id, { duration_seconds: Number(event.currentTarget.value) })} />
                </label>
                <label className="creative-field" htmlFor={`scene-status-${scene.id}`}>Scene status
                  <select id={`scene-status-${scene.id}`} value={scene.status} onChange={(event) => updateScene(scene.id, { status: event.currentTarget.value as ProjectStoryboardScene["status"] })}><option value="draft">Draft</option><option value="ready_for_review">Ready for review</option></select>
                </label>
                <TextAreaField id={`scene-description-${scene.id}`} label="Description" value={scene.description} maxLength={500} onChange={(value) => updateScene(scene.id, { description: value })} />
                <TextAreaField id={`scene-visual-${scene.id}`} label="Visual direction" value={scene.visual_direction} maxLength={1000} onChange={(value) => updateScene(scene.id, { visual_direction: value })} />
                <TextAreaField id={`scene-screen-text-${scene.id}`} label="On-screen text" value={scene.on_screen_text} maxLength={500} onChange={(value) => updateScene(scene.id, { on_screen_text: value })} />
                <TextAreaField id={`scene-narration-${scene.id}`} label="Voiceover / narration notes" value={scene.narration} maxLength={1000} onChange={(value) => updateScene(scene.id, { narration: value })} />
              </div>
            </li>)}
          </ol>
        )}
        <button type="button" className="projects-secondary-action" disabled={draft.storyboard.length >= 32} onClick={addScene}>Add scene</button>
        <p className="creative-field-hint">Scene status is editorial only. It does not indicate rendering or production readiness.</p>
      </fieldset>

      <div className="creative-save-row">
        <p className="creative-save-state">{isDirty ? "Unsaved changes" : "All changes saved"}</p>
        <button className="projects-primary-action" type="button" disabled={saving || !isDirty} onClick={() => void saveWorkspace()}>{saving ? "Saving…" : "Save workspace"}</button>
      </div>
      {saveError && <p className="projects-message projects-message-error" role="alert">{saveError}</p>}
      {hasRevisionConflict && <button className="projects-secondary-action" type="button" onClick={() => void loadWorkspace()} aria-label="Discard unsaved edits and reload the saved workspace">Discard local edits and reload saved version</button>}
      {notice && <p className="projects-message" role="status">{notice}</p>}
    </section>
  </div>;
}

function ReadinessItem({ complete, label, detail }: { complete: boolean; label: string; detail: string }) {
  return <li className="creative-readiness-item"><span className={complete ? "readiness-mark is-complete" : "readiness-mark"} aria-hidden="true">{complete ? "✓" : "—"}</span><span><strong>{label}</strong><small>{detail}</small></span></li>;
}

function TextField({ id, label, value, maxLength, onChange, type = "text" }: { id: string; label: string; value: string; maxLength: number; onChange: (value: string) => void; type?: string }) {
  return <label className="creative-field" htmlFor={id}>{label}<input id={id} type={type} maxLength={maxLength} value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function TextAreaField({ id, label, value, maxLength, onChange }: { id: string; label: string; value: string; maxLength: number; onChange: (value: string) => void }) {
  return <label className="creative-field" htmlFor={id}>{label}<textarea id={id} rows={2} maxLength={maxLength} value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function SelectField({ id, label, value, options, onChange }: { id: string; label: string; value: string; options: [string, string][]; onChange: (value: string) => void }) {
  return <label className="creative-field" htmlFor={id}>{label}<select id={id} value={value} onChange={(event) => onChange(event.currentTarget.value)}>{options.map(([option, text]) => <option key={option || "empty"} value={option}>{text}</option>)}</select></label>;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unavailable" : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}
