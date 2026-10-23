"use client";

import Link from "next/link";
import { useNorthstarProjectState } from "../demo-project-provider";
import { calculateStoryboardRuntime, isValidStoryboardDuration } from "../storyboard-model";

export default function StoryboardWorkspace() {
  const { brief, scenes, updateScene, addScene, deleteScene, moveScene, resetStoryboard } = useNorthstarProjectState();
  const plannedRuntime = calculateStoryboardRuntime(scenes.map((scene) => scene.durationSeconds));
  const invalidSceneCount = scenes.filter((scene) => !scene.title.trim() || !isValidStoryboardDuration(scene.durationSeconds)).length;

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
        <div><h2 id="storyboard-notice-title">Illustrative storyboard · temporary in-memory state</h2><p>All scenes and copy are demo examples. Changes are shared across Northstar project routes in this tab and reset when you refresh. No production or generation is connected.</p></div>
      </aside>

      <section className="storyboard-overview" aria-label="Storyboard summary" aria-live="polite">
        <div><span>Scenes</span><strong>{scenes.length}</strong></div>
        <div><span>Planned runtime</span><strong>{plannedRuntime === null ? "Unavailable" : `${plannedRuntime} sec`}</strong></div>
        <div><span>Brief target</span><strong>{brief.duration} sec</strong></div>
        <div><span>Aspect ratio</span><strong>{brief.aspectRatio}</strong></div>
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

                      <label htmlFor={`storyboard-narration-${scene.id}`}>Voiceover / narration</label>
                      <textarea id={`storyboard-narration-${scene.id}`} rows={2} value={scene.narration} onChange={(event) => updateScene(scene.id, { narration: event.currentTarget.value })} />

                      <label htmlFor={durationId}>Duration <span>(1–60 seconds)</span></label>
                      <input id={durationId} type="number" min={1} max={60} step={1} value={scene.durationSeconds} aria-invalid={durationInvalid} aria-describedby={durationInvalid ? durationErrorId : undefined} onChange={(event) => updateScene(scene.id, { durationSeconds: event.currentTarget.value === "" ? 0 : Number(event.currentTarget.value) })} />
                      {durationInvalid && <p className="storyboard-field-error" id={durationErrorId}>Use a whole-number duration from 1 to 60 seconds.</p>}

                      <label htmlFor={`storyboard-transition-${scene.id}`}>Transition or editing note</label>
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
        <div><p className="storyboard-kicker">Production boundary</p><h2 id="storyboard-production-title">A storyboard is not a finished ad.</h2><p>No footage, voiceover, artwork, or video is generated here. Ad generation remains unavailable in this demo.</p></div>
        <button className="storyboard-reset" type="button" onClick={confirmReset}>Reset to demo storyboard</button>
      </section>

      <footer className="storyboard-footer"><p>Illustrative only · No real business claims verified · Changes reset on refresh</p><div><Link href="/projects/sample-northstar/brief">Creative brief</Link><Link href="/projects/sample-northstar/review">Fact review</Link><Link href="/projects/sample-northstar/creative">Creative readiness</Link><Link href="/projects/sample-northstar">Sample project</Link></div></footer>
    </div>
  );
}
