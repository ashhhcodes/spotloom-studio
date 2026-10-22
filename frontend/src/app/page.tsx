import { ThemePicker } from "@/components/theme-picker";
import "./page.css";

const colors = [
  { name: "Paper", token: "canvas", value: "#F3EFE7", className: "swatch-paper" },
  { name: "Ink", token: "ink", value: "#242522", className: "swatch-ink" },
  { name: "Vermilion", token: "accent", value: "#D94D35", className: "swatch-vermilion" },
  { name: "Sage", token: "sage", value: "#A6AD9A", className: "swatch-sage" },
];

export default function Home() {
  return (
    <main className="studio-page">
      <header className="masthead">
        <a className="wordmark" href="#top" aria-label="Spotloom Studio home">
          <span className="wordmark-mark" aria-hidden="true"><span /></span>
          <span>Spotloom <span className="wordmark-light">Studio</span></span>
        </a>
        <p className="masthead-edition">Design foundation <span>—</span> 01</p>
        <ThemePicker />
      </header>

      <section className="intro" id="top" aria-labelledby="intro-title">
        <p className="eyebrow"><span className="eyebrow-line" /> An independent creative workspace</p>
        <div className="intro-grid">
          <p className="intro-index">A / 01</p>
          <div className="intro-copy">
            <h1 id="intro-title">Make room<br />for the <em>idea.</em></h1>
            <div className="intro-foot">
              <p>A warm, deliberate visual language for shaping clear campaign work. Built on paper, ink, and a little vermilion.</p>
              <a className="text-link" href="#materials">Explore the materials <span aria-hidden="true">↘</span></a>
            </div>
          </div>
          <div className="intro-aside" aria-label="Design principle">
            <span className="aside-rule" />
            <p>Clarity before spectacle.<br />Room for the work.</p>
            <span className="aside-number">SYSTEM / 01</span>
          </div>
        </div>
      </section>

      <section className="work-sample" aria-labelledby="sample-title">
        <div className="sample-topline">
          <p className="section-label">In practice <span>／</span> Copy and color</p>
          <p className="sample-meta">Sample business · Coffee</p>
        </div>
        <div className="sample-artboard">
          <div className="sample-mark" aria-hidden="true">N<span>.</span></div>
          <div className="sample-copy">
            <p className="sample-kicker">NORTHSTAR COFFEE <span>·</span> SMALL BATCH</p>
            <h2 id="sample-title">A good cup,<br /><em>made simple.</em></h2>
            <div className="sample-bottom">
              <p>Small-batch coffee, thoughtfully roasted.</p>
              <span className="sample-cta">Find your next cup <span aria-hidden="true">↗</span></span>
            </div>
          </div>
          <span className="sample-orbit orbit-one" aria-hidden="true" />
          <span className="sample-orbit orbit-two" aria-hidden="true" />
          <span className="sample-caption">COPY SPECIMEN · 01</span>
        </div>
      </section>

      <section className="materials section-block" id="materials" aria-labelledby="materials-title">
        <div className="section-heading">
          <p className="section-index">01 <span>—</span> Materials</p>
          <div>
            <h2 id="materials-title">A palette with purpose.</h2>
            <p className="section-description">Semantic color roles keep the interface coherent across light and dark surfaces.</p>
          </div>
        </div>
        <div className="swatch-grid">
          {colors.map((color) => (
            <div className="swatch-item" key={color.token}>
              <div className={`swatch ${color.className}`} aria-label={`${color.name} color sample`} />
              <div className="swatch-caption">
                <span>{color.name}</span>
                <code>--{color.token}</code>
                <code>{color.value}</code>
              </div>
            </div>
          ))}
        </div>
        <div className="semantic-row" aria-label="Semantic color tokens">
          <span><i className="status-dot status-success" />Success · Confirmed</span>
          <span><i className="status-dot status-warning" />Review · Needs attention</span>
          <span><i className="status-dot status-danger" />Error · Action required</span>
          <span className="contrast-note">Status always includes a label.</span>
        </div>
      </section>

      <section className="type-section section-block" id="type" aria-labelledby="type-title">
        <div className="section-heading">
          <p className="section-index">02 <span>—</span> Typography</p>
          <div>
            <h2 id="type-title">Character, with clarity.</h2>
            <p className="section-description">A local-first font pairing: expressive editorial serif, practical system sans.</p>
          </div>
        </div>
        <div className="type-specimens">
          <div className="type-display">
            <span className="type-label">DISPLAY / SERIF</span>
            <p>Good work<br />has a point of view.</p>
          </div>
          <div className="type-detail">
            <div>
              <span className="type-label">BODY / SYSTEM SANS</span>
              <p className="body-sample">Give every idea enough space to become clear. Keep the tools close, the language direct, and the work at the center.</p>
            </div>
            <div className="type-scale">
              <span className="type-label">TYPE SCALE</span>
              <p><strong>Page title</strong><small>48–88 / editorial</small></p>
              <p><strong>Section heading</strong><small>26–36 / sans</small></p>
              <p><strong>Body and labels</strong><small>14–17 / sans</small></p>
            </div>
          </div>
        </div>
      </section>

      <section className="controls-section section-block" id="controls" aria-labelledby="controls-title">
        <div className="section-heading">
          <p className="section-index">03 <span>—</span> Interface details</p>
          <div>
            <h2 id="controls-title">Quietly useful.</h2>
            <p className="section-description">Fine borders, compact controls, visible focus, and a measured spacing rhythm.</p>
          </div>
        </div>
        <div className="details-grid">
          <div className="control-specimen">
            <label className="field-label" htmlFor="business-name">Business name <span>EXAMPLE FIELD</span></label>
            <input id="business-name" className="text-input" defaultValue="Northstar Coffee" />
            <p className="field-help">A clear label and calm, legible input state.</p>
            <a className="button button-primary" href="#materials">Explore the palette <span aria-hidden="true">↘</span></a>
          </div>
          <div className="spacing-specimen">
            <span className="type-label">SPACING RHYTHM</span>
            {["06", "12", "16", "24", "32", "48"].map((size, index) => (
              <div className="space-row" key={size}>
                <code>{size}</code><span className="space-bar" style={{ width: `${(index + 1) * 18}px` }} /><small>{["xs", "sm", "md", "lg", "xl", "2xl"][index]}</small>
              </div>
            ))}
          </div>
          <div className="surface-specimen">
            <span className="type-label">SURFACE / HAIRLINE</span>
            <div className="surface-example">
              <span className="surface-square" aria-hidden="true" />
              <p>Paper surface<br /><small>Fine border · soft edge</small></p>
              <span className="surface-count">01</span>
            </div>
            <p className="field-help">No glow, no glass. Hierarchy comes from contrast and alignment.</p>
          </div>
        </div>
      </section>

      <footer className="page-footer">
        <a className="wordmark footer-wordmark" href="#top">
          <span className="wordmark-mark" aria-hidden="true"><span /></span>
          <span>Spotloom <span className="wordmark-light">Studio</span></span>
        </a>
        <p>DESIGN FOUNDATION <span>·</span> PHASE 01</p>
        <a className="footer-top" href="#top">Back to top <span aria-hidden="true">↑</span></a>
      </footer>
    </main>
  );
}
