# Spotloom Studio — design foundation

This folder contains the Spotloom Studio frontend, its editorial design system, and the Northstar Coffee illustrative project workflow. Only Creative Readiness has an explicit connection to the local pre-production validation API; other project workflows remain frontend-only.

## Requirements

- Node.js 20.9 or newer
- npm

Install dependencies and start the local development server from this folder:

```powershell
npm install
npm run dev
```

Open <http://localhost:3000>. The appearance starts in **System** mode and follows the operating system color preference. The selector can temporarily switch to Light or Dark for review; the initial implementation does not persist that choice.

Quality checks:

```powershell
npm run lint
npm run typecheck
npm run build
```

## Local pre-production evaluation

Creative Readiness keeps its live local validator as a separate reference and can explicitly submit the current facts, brief, and ordered storyboard scenes to `POST /validate/preproduction`. No request is sent automatically. The backend returns structural findings and runtime; it does not verify facts, authorize work, persist project state, or generate an advertisement. Caller-marked fact approval and brief confirmation are submitted values, not authenticated decisions.

Start the backend in one PowerShell window:

```powershell
cd D:\AdForge_AI\backend
..\.venv\Scripts\Activate.ps1
python -m adforge_renderer.api
```

Start the frontend in another window:

```powershell
cd D:\AdForge_AI\frontend
npm run dev
```

The Next.js development server proxies only `/api/adforge/validate/preproduction` to the configured backend, so the browser uses a same-origin request without changing backend CORS settings. The base URL defaults to `http://127.0.0.1:8000`. To change it, create `frontend/.env.local` with a public, non-secret URL:

```dotenv
NEXT_PUBLIC_ADFORGE_API_BASE_URL=http://127.0.0.1:8000
```

Restart the frontend after changing this value. It is public configuration, not a place for credentials. The local and backend validators are not identical: backend schema violations return sanitized HTTP 422 issues; the local validator can represent some malformed states as findings. The backend also cannot infer whether brief values came from demo defaults. See the integration contract for the complete parity matrix and limitations.

### Manual browser QA for Creative Readiness

The frontend package has no React component or browser automation test runner. For a manual reliability check, start both services and open `/projects/sample-northstar/creative`:

1. With browser DevTools Network open and request throttling enabled, activate **Evaluate with backend** by mouse, then repeat using Tab plus Enter or Space. Confirm one POST is sent, the button is disabled while pending, and the loading status is announced.
2. During a pending request, navigate to Fact Review, approve or correct a fact, then return to Creative Readiness. Confirm no old response appears and the page is not stuck loading. Repeat by changing a brief field and reordering a storyboard scene.
3. Complete an evaluation, then leave the route and change a submitted field. Return and confirm the prior page-local result is cleared; submit again and confirm the new response is distinct from the local reference section.
4. Stop the backend, request evaluation, and confirm a safe retry message appears without stack details. Restart the backend and retry without refreshing. For a schema error, submit an over-limit brief field and confirm only sanitized field paths/messages are shown.
5. Use keyboard-only navigation and a screen reader to verify the visible focus ring, disabled/loading announcement, successful status, assertive error announcement, findings headings, and that Generate Ad remains disabled.

Results are held only by the Creative Readiness page and are discarded on route navigation or refresh. Northstar facts, brief, and storyboard continue to use the existing shared in-memory provider and reset on refresh.
