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
