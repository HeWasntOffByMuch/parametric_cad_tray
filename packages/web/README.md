# traymold web

React + TypeScript + Vite + React Three Fiber. Static build; the backend is
configured at runtime, so one bundle serves any deployment.

```bash
npm install
npm run dev        # expects the API on :8000, proxied via /api
npm run test
npm run build      # relative asset URLs: works under a GitHub Pages repo path
```

Or from the repository root, `make dev` runs the API, its CAD worker pool and
Vite together.

## Pointing at a backend

Most specific first:

1. `?api=https://api.example.com` — also remembered in localStorage
2. `window.__TRAYMOLD_API_BASE__` — edit the deployed `index.html`
3. `VITE_API_BASE_URL` — baked in at build time
4. same origin — what the dev server proxies

## What is not here

The parameter schema. It is served by `GET /api/schema` and the form is rendered
from it, so adding a parameter to the geometry core surfaces it in the UI with no
change in this package. `src/api/types.ts` types the transport envelopes only.

Any CAD maths. The GLB from the backend is authoritative; the viewer uses its
`male` and `female` nodes directly.

See `docs/frontend.md` for the preview state machine, staleness rules and
deployment notes.
