"use client";

import Link from "next/link";
import { useNorthstarProjectState } from "../demo-project-provider";
import {
  calculateIllustrativeRenderRuntime,
  calculateStoryboardRuntime,
  isValidStoryboardDuration,
  MAX_ILLUSTRATIVE_RENDER_SECONDS,
  STORYBOARD_FADE_SECONDS,
} from "../storyboard-model";

export default function StoryboardWorkspace() {
  const { brief, scenes, brandPalette, updateBrandPalette, updateScene, addScene, deleteScene, moveScene, resetStoryboard } = useNorthstarProjectState();
  const plannedRuntime = calculateStoryboardRuntime(scenes.map((scene) => scene.durationSeconds));
  const renderRuntime = calculateIllustrativeRenderRuntime(scenes);
  const invalidSceneCount = scenes.filter((scene) => !scene.title.trim() || !isValidStoryboardDuration(scene.durationSeconds)).length;
  const invalidBrandColor = ![brandPalette.primary, brandPalette.accent].every((color) => /^#[0-9A-Fa-f]{6}$/.test(color));

  function confirmReset() {
    if (window.confirm("Reset the storyboard to its illustrative Northstar demo scenes?")) resetStoryboard();
  }

  return (
    <div className="storyboard-page">
      <nav className="storyboard-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li><Link href="/#overview">Overview</Link></li>
          <li><Link href="/projects/sample-northstar">Northstar Coffee sample</Link></li>
          <li aria-current="page">Storyboard</li>
        </ol>
      </nav>

      <header className="storyboard-heading">
        <p className="storyboard-kicker">Northstar Coffee <span aria-hidden="true">/</span> Illustrative sample</p>
        <h1>Plan the<br /><em>scenes.</em></h1>
        <p>Arrange a possible story beat by beat. This is a planning document only; it does not create footage, narration, or an advertisement.</p>
      </header>

      <aside className="storyboard-notice" aria-labelledby="storyboard-notice-title">
        <span aria-hidden="true">i</span>
        <div><h2 id="storyboard-notice-title">Illustrative storyboard · temporary in-memory state</h2><p>All scenes and copy are demo examples. Changes are shared across Northstar project routes in this tab and reset when you refresh. Creative Readiness can render a temporary silent video using these scene durations and supported transitions.</p></div>
      </aside>

      <section className="storyboard-overview" aria-label="Storyboard summary" aria-live="polite">
        <div><span>Scenes</span><strong>{scenes.length}</strong></div>
        <div><span>Planned runtime</span><strong>{plannedRuntime === null ? "Unavailable" : `${plannedRuntime} sec`}</strong></div>
        <div><span>Brief target</span><strong>{brief.duration} sec</strong></div>
        <div><span>Aspect ratio</span><strong>{brief.aspectRatio}</strong></div>
      </section>

      <p className="storyboard-validation-summary" role="status">
        Illustrative render timeline: {renderRuntime === null ? "unavailable" : `${renderRuntime.toFixed(2)} sec`} after {STORYBOARD_FADE_SECONDS}-second fades. Local render limit: {MAX_ILLUSTRATIVE_RENDER_SECONDS} seconds.
        {renderRuntime !== null && renderRuntime > MAX_ILLUSTRATIVE_RENDER_SECONDS ? " Shorten scene durations before rendering." : ""}
      </p>

      <section className="storyboard-brand-profile" aria-labelledby="storyboard-brand-title">
        <div><p className="storyboard-kicker">Shared render styling</p><h2 id="storyboard-brand-title">Illustrative brand palette</h2><p>These demo colors are sent with Generate Ad and applied consistently across all scene layouts. They reset when you refresh.</p></div>
        <div className="storyboard-brand-colors">
          <label htmlFor="storyboard-brand-primary">Primary color <span className="storyboard-brand-swatch" aria-hidden="true" style={{ backgroundColor: /^#[0-9A-Fa-f]{6}$/.test(brandPalette.primary) ? brandPalette.primary : "transparent" }} /><input id="storyboard-brand-primary" type="text" inputMode="text" autoComplete="off" spellCheck={false} maxLength={7} pattern="#[0-9A-Fa-f]{6}" aria-invalid={!/^#[0-9A-Fa-f]{6}$/.test(brandPalette.primary)} value={brandPalette.primary} onChange={(event) => updateBrandPalette({ primary: event.currentTarget.value })} /></label>
          <label htmlFor="storyboard-brand-accent">Accent color <span className="storyboard-brand-swatch" aria-hidden="true" style={{ backgroundColor: /^#[0-9A-Fa-f]{6}$/.test(brandPalette.accent) ? brandPalette.accent : "transparent" }} /><input id="storyboard-brand-accent" type="text" inputMode="text" autoComplete="off" spellCheck={false} maxLength={7} pattern="#[0-9A-Fa-f]{6}" aria-invalid={!/^#[0-9A-Fa-f]{6}$/.test(brandPalette.accent)} value={brandPalette.accent} onChange={(event) => updateBrandPalette({ accent: event.currentTarget.value })} /></label>
        </div>
        <p className="storyboard-brand-format" role={invalidBrandColor ? "alert" : undefined}>{invalidBrandColor ? "Enter both colors as #RRGGBB before rendering." : "Enter colors in #RRGGBB format."}</p>
      </section>

      {invalidSceneCount > 0 && <p className="storyboard-validation-summary" role="status">{invalidSceneCount} {invalidSceneCount === 1 ? "scene needs" : "scenes need"} attention: enter a title and a whole-number duration from 1 to 60 seconds.</p>}

      <section className="storyboard-scenes" aria-labelledby="storyboard-scenes-title">
        <div className="storyboard-section-heading"><div><p className="storyboard-kicker">Sequence <span aria-hidden="true">·</span> demo plan</p><h2 id="storyboard-scenes-title">Scene outline</h2></div><button className="storyboard-add" type="button" onClick={addScene}>Add scene <span aria-hidden="true">＋</span></button></div>
        {scenes.length === 0 ? <p className="storyboard-empty">No scenes yet. Add a scene to begin the illustrative outline.</p> : (
          <ol className="storyboard-scene-list">
            {scenes.map((scene, index) => {
              const titleId = `storyboard-title-${scene.id}`;
              const titleErrorId = `${titleId}-error`;
              const durationId = `storyboard-duration-${scene.id}`;
              const durationErrorId = `${durationId}-error`;
              const transitionId = `storyboard-render-transition-${scene.id}`;
              const roleId = `storyboard-render-role-${scene.id}`;
              const defaultRole = index === 0 ? "hook" : index === scenes.length - 1 ? "cta" : "benefit";
              const titleInvalid = !scene.title.trim();
              const durationInvalid = !isValidStoryboardDuration(scene.durationSeconds);
              return (
                <li className="storyboard-scene" key={scene.id}>
                  <article>
                    <header className="storyboard-scene-header">
                      <div><p className="storyboard-scene-number">SCENE {String(index + 1).padStart(2, "0")}</p><h3>{scene.title.trim() || "Untitled scene"}</h3></div>
                      <div className="storyboard-order-controls" aria-label={`Order controls for scene ${index + 1}`}>
                        <button type="button" aria-label={`Move scene ${index + 1} up`} onClick={() => moveScene(scene.id, -1)} disabled={index === 0}>Move up <span aria-hidden="true">↑</span></button>
                        <button type="button" aria-label={`Move scene ${index + 1} down`} onClick={() => moveScene(scene.id, 1)} disabled={index === scenes.length - 1}>Move down <span aria-hidden="true">↓</span></button>
                        <button type="button" className="storyboard-delete" aria-label={`Delete scene ${index + 1}`} onClick={() => deleteScene(scene.id)}>Delete</button>
                      </div>
                    </header>
                    <div className="storyboard-fields">
                      <label htmlFor={titleId}>Scene title</label>
                      <input id={titleId} value={scene.title} aria-invalid={titleInvalid} aria-describedby={titleInvalid ? titleErrorId : undefined} onChange={(event) => updateScene(scene.id, { title: event.currentTarget.value })} />
                      {titleInvalid && <p className="storyboard-field-error" id={titleErrorId}>Enter a title for this scene.</p>}

                      <label htmlFor={`storyboard-purpose-${scene.id}`}>Narrative purpose</label>
                      <textarea id={`storyboard-purpose-${scene.id}`} rows={2} value={scene.narrativePurpose} onChange={(event) => updateScene(scene.id, { narrativePurpose: event.currentTarget.value })} />

                      <label htmlFor={`storyboard-visual-${scene.id}`}>Visual direction</label>
                      <textarea id={`storyboard-visual-${scene.id}`} rows={2} value={scene.visualDirection} onChange={(event) => updateScene(scene.id, { visualDirection: event.currentTarget.value })} />

                      <label htmlFor={`storyboard-text-${scene.id}`}>On-screen text</label>
                      <textarea id={`storyboard-text-${scene.id}`} rows={2} value={scene.onScreenText} onChange={(event) => updateScene(scene.id, { onScreenText: event.currentTarget.value })} />

                      <label htmlFor={roleId}>Rendered scene layout</label>
                      <select id={roleId} value={scene.role ?? defaultRole} onChange={(event) => updateScene(scene.id, { role: event.currentTarget.value as "hook" | "benefit" | "proof" | "cta" })}>
                        <option value="hook">Hook · bold opening</option>
                        <option value="benefit">Benefit · feature focus</option>
                        <option value="proof">Proof · supporting detail</option>
                        <option value="cta">CTA · closing action</option>
                      </select>

                      <label htmlFor={`storyboard-narration-${scene.id}`}>Voiceover / narration</label>
                      <textarea id={`storyboard-narration-${scene.id}`} rows={2} value={scene.narration} onChange={(event) => updateScene(scene.id, { narration: event.currentTarget.value })} />

                      <label htmlFor={durationId}>Duration <span>(1–60 seconds)</span></label>
                      <input id={durationId} type="number" min={1} max={60} step={1} value={scene.durationSeconds} aria-invalid={durationInvalid} aria-describedby={durationInvalid ? durationErrorId : undefined} onChange={(event) => updateScene(scene.id, { durationSeconds: event.currentTarget.value === "" ? 0 : Number(event.currentTarget.value) })} />
                      {durationInvalid && <p className="storyboard-field-error" id={durationErrorId}>Use a whole-number duration from 1 to 60 seconds.</p>}

                      <label htmlFor={transitionId}>Rendered transition into this scene</label>
                      <select id={transitionId} value={index === 0 ? "cut" : scene.transition} disabled={index === 0} onChange={(event) => updateScene(scene.id, { transition: event.currentTarget.value as "cut" | "fade" })}>
                        <option value="cut">Cut (no overlap)</option>
                        <option value="fade">Crossfade ({STORYBOARD_FADE_SECONDS} seconds)</option>
                      </select>
                      {index === 0 && <p className="storyboard-field-hint">The first scene starts directly without an incoming transition.</p>}

                      <label htmlFor={`storyboard-transition-${scene.id}`}>Transition or editing note <span>(not rendered)</span></label>
                      <textarea id={`storyboard-transition-${scene.id}`} rows={2} value={scene.transitionNote} onChange={(event) => updateScene(scene.id, { transitionNote: event.currentTarget.value })} />
                    </div>
                  </article>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <section className="storyboard-production-note" aria-labelledby="storyboard-production-title">
        <div><p className="storyboard-kicker">Production boundary</p><h2 id="storyboard-production-title">A storyboard is not a finished ad.</h2><p>This editor does not create footage, voiceover, or artwork. Use Creative Readiness for a temporary silent illustrative MP4 from each scene’s title, on-screen text, selected layout, duration, and cut or crossfade transition.</p></div>
        <button className="storyboard-reset" type="button" onClick={confirmReset}>Reset to demo storyboard</button>
      </section>

      <footer className="storyboard-footer"><p>Illustrative only · No real business claims verified · Changes reset on refresh</p><div><Link href="/projects/sample-northstar/brief">Creative brief</Link><Link href="/projects/sample-northstar/review">Fact review</Link><Link href="/projects/sample-northstar/creative">Creative readiness</Link><Link href="/projects/sample-northstar">Sample project</Link></div></footer>
    </div>
  );
}
