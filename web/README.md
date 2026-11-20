# Mira website

A one-page, mobile-first Next.js app. Pick the map and who picks first, enter bans and picks as they
happen, and get pick/ban suggestions plus the most likely line for the rest of the draft.

```sh
npm install
npm run dev      # http://localhost:3000 (Agentation feedback toolbar shows in dev only)
npm test         # engine parity with the Python reference + draft-state tests
npm run build
```

- **No server work:** the page is static. `public/model.json` is loaded in the browser and the
  draft search runs client-side (`src/engine/`, a port of `src/mira/engine/` in the Python package).
- **Updating the model:** from the repo root run `uv run mira train && uv run mira publish`. This
  copies `model.json` here and regenerates `src/engine/parity.fixtures.json`. Then run `npm test`
  and commit.
- **Design:** tokens and motion follow `jmo-workflow:better-ui`, defined in `src/app/globals.css`:
  shadow rings with transparent borders, concentric radii, press scale 0.96, motion gated on
  `prefers-reduced-motion`, and hover styles only on hover-capable pointers.
- **Deploying:** on Vercel, set the project's root directory to `web/`.
