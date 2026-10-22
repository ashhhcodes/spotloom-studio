# Design System — AdForge AI

- Status: Proposed
- Goal: Intentional, product-specific interface that does not resemble a generic AI dashboard.

## 1. Visual concept
AdForge AI should feel like a creative production studio: confident, editorial, visual, and focused on the generated advertisement. The interface should give the video preview and user decisions more prominence than generic cards or decorative gradients.

Avoid:
- Default purple/blue AI gradients everywhere.
- Excessive glassmorphism and glowing borders.
- Repeated rounded cards for every text block.
- Emoji as the primary icon system.
- Decorative charts that do not represent real data.
- Placeholder buttons that do nothing.
- Large hero copy that pushes the actual product below the fold.

## 2. Suggested direction
- Base: warm near-white or deep charcoal, chosen consistently.
- Accent: controlled vermilion/red or a distinctive warm accent; avoid using color as the only status indicator.
- Typography: one expressive display family for headings plus a highly legible UI sans-serif.
- Layout: strong grid, deliberate whitespace, clear left-to-right workflow, large preview canvas.
- Icons: consistent Lucide-style outline icons.
- Motion: restrained transitions; respect reduced-motion preferences.

Exact colors and fonts should be selected after a quick visual exploration and recorded as tokens before coding.

## 3. Main screens

### Landing/Create
- Concise value proposition.
- Prominent URL input and primary action.
- Manual mode as a clear alternative.
- Example output preview.
- No fake testimonials or unsupported performance claims.

### Facts review
- Business facts grouped logically.
- Source/provenance visible but not noisy.
- Missing/conflicting facts clearly marked.
- Easy edit/approve actions.
- Candidate images with selection state.

### Creative configuration
- Goal, tone, duration, aspect ratio, CTA and visual style.
- Sensible defaults.
- Provider-dependent options disabled with explanation when unavailable.

### Creative review
- Hook and scene timeline.
- On-screen copy and asset assignment.
- Show which facts support critical claims.
- Edit before rendering.

### Generation
- Clear stage progress and elapsed time.
- Explain current operation.
- Allow cancellation where safe.
- Do not fake percentage precision if progress is indeterminate.

### Result
- Video preview as the visual focus.
- Download action.
- Format, duration, provider/fallback disclosure.
- Warnings and composition summary.
- Retry action only when safe and understandable.

## 4. Design tokens
Define tokens centrally for:
- Color roles: background, surface, text, muted, border, primary, destructive, success, warning.
- Typography: display, heading, body, caption, code.
- Spacing scale.
- Radius scale.
- Shadows.
- Focus ring.
- Motion duration/easing.
- Breakpoints.

Avoid hard-coding one-off values throughout components.

## 5. Component quality
Reusable components should include:
- Button variants and disabled/loading states.
- Input with label, help and error.
- Select and segmented control.
- Status indicator.
- Alert/warning.
- Progress/stage timeline.
- Asset thumbnail and picker.
- Video preview.
- Empty state and error state.
- Dialog for destructive/retry actions.

## 6. Responsive behavior
- Desktop: workflow controls and large preview can sit side-by-side where appropriate.
- Tablet: reduce columns while preserving clear hierarchy.
- Mobile: single-column workflow, touch-friendly controls, readable video preview, no horizontal overflow.

## 7. Visual QA checklist
- Inspect desktop and mobile screenshots.
- Test long business names and long CTA copy.
- Test missing logo/image/offer.
- Test slow loading, partial scan, provider failure and fallback.
- Verify contrast, keyboard focus and labels.
- Ensure disabled controls explain why.
- Confirm all visible controls work.
- Compare implementation against the chosen design references.
