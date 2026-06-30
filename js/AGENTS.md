# dimos-js — conventions

The `js/` Bun + Turbo workspace: the `@dimos/*` TS libraries and the web apps
(dimoscope) for the DimOS bus. Aligned to the house style of the sibling repos
`styld` and `invok`. Read this before adding code.

## Toolchain

- **Bun** package manager + **Turbo** task runner. Versions are pinned once in
  the root `package.json` **`catalog`**; packages reference them with
  `"catalog:"` — never hand-pin a version that's in the catalog.
- **Lint**: `oxlint` (extends `ultracite/oxlint/core`, type-aware via
  `oxlint-tsgolint`). **Format**: `oxfmt` (`.oxfmtrc.jsonc`). Run `bun run fix`
  before committing; `bun run check` is the read-only gate.
- **Type-check**: TypeScript 6 via **tsgo** (`@typescript/native-preview`);
  every package has `"typecheck": "tsgo --noEmit"`. Strict base in
  `tsconfig.base.json` (`noUncheckedIndexedAccess`, `verbatimModuleSyntax`,
  `isolatedModules`, …) — extend it, don't relax it.

## Code style

- **Services are functional factories**: `export const createX = (deps) => ({ … })`,
  dependencies injected via a single `deps`/`opts` object (closures). A `class`
  is acceptable **only** for a genuinely stateful piece (e.g. a transport with a
  socket), and it must still be wrapped by a `createX` factory as the public
  entry. No class-based "services".
- **Errors**: use **`errore`** tagged errors (`createTaggedError`). Return errors
  as values for expected failures (`T | DecodeError`); reserve `throw` for
  programmer errors / the outermost boundary.
- **Logging**: no logging framework — the gateway is a thin byte-relay and uses
  `console.*` directly; the SDK/library code stays silent.
- **Runtime validation**: **`zod`** (catalog-pinned) for anything crossing a
  boundary — the gateway WS control-plane messages, `connect()` options/config.
  Binary bus messages are decoded by `@dimos/msgs` (generated codec), not zod.

## Packages

- Internal packages ship **TypeScript source** via `exports` (no build step) —
  consumed across the workspace with `workspace:*`.
- **Publishable** packages (`@dimos/msgs`, `@dimos/lcm`, `@dimos/topics`,
  `@dimos/react`) build with **tsdown → `dist`** (`types`/`import`), `files: ["dist"]`,
  and publish to **npm**.
- Generated code lives in `generated/` and is lint/format-ignored.

## Not applicable here (do NOT add)

This is a robotics bus SDK + web apps — there is no database, HTTP-CRUD API,
auth, or persisted entities. Do **not** introduce drizzle, oRPC, better-auth,
typeid-js, or similar; they are house tools for the _product_ repos, not here.

## Adding a package

1. `js/packages/<name>/package.json` (`"name": "@dimos/<name>"`, `type: module`,
   deps via `catalog:` / `workspace:*`, `"typecheck": "tsgo --noEmit"`,
   `"lint": "oxlint --type-aware --type-check ."`).
2. `js/packages/<name>/tsconfig.json` extending `../../tsconfig.base.json`.
3. Internal → `exports` points at `./src/*.ts`; publishable → add `tsdown` build.
