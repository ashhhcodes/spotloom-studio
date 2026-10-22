# Spotloom Studio — design foundation

This folder contains the Phase 1 frontend foundation: a responsive visual specimen page, centralized design tokens, and a system-aware light/dark theme selector. The application shell and backend integration are intentionally out of scope.

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
