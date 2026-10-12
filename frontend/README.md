# DealScope web frontend

React 18 + TypeScript + Vite single-page app for the DealScope FastAPI server.

## Install

    npm install

## Develop

    npm run dev

Opens on http://localhost:5173. Requests to `/api` are proxied to `http://127.0.0.1:8000`, so start the
FastAPI server first.

To explore the UI without a backend, run with the dev-only mock API:

    VITE_USE_MOCKS=true npm run dev

(On Windows PowerShell: `$env:VITE_USE_MOCKS="true"; npm run dev`.) The mock code is never included in
production builds.

## Build

    npm run build      # type-check (tsc --noEmit) then vite build -> dist/
    npm run typecheck  # tsc --noEmit only (alias: npm run lint)

The production bundle is written to `frontend/dist`, which the FastAPI server serves.

## Layout

- `src/api` - API types (fixed contract) and the typed fetch client
- `src/content` - types for the "How it works" content, and the content itself
- `src/components` - presentational pieces (case sections, forms, tables)
- `src/pages` - routed pages: New investigation, Cases, Case detail, How it works
- `src/lib` - formatting helpers and data-loading hooks (including case polling)
- `src/mocks` - dev-only mock backend
