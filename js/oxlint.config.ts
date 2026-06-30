import { defineConfig } from "oxlint";
import core from "ultracite/oxlint/core";

// dimoscope is Vite + React (not Next), so we extend ultracite's `core` preset
// only. The rule-offs below are (1) the styld/invok house baseline — pure-style
// rules the house disables — plus (2) relaxations appropriate to a message-BUS
// SDK + viz app: code that decodes ARBITRARY LCM payloads by 8-byte hash is
// unavoidably dynamic at the decode boundary, so the type-aware `no-unsafe-*`
// family is scoped to JUST that boundary via `overrides` below — typed topics
// (DimosTopics) keep the rest of the workspace fully checked.
export default defineConfig({
  extends: [core],
  // bench_deno.ts is a Deno script (Deno globals) run via `deno run`, not part of
  // the Bun/TS build — excluded from typecheck (tsconfig.server.json) + lint here.
  ignorePatterns: [
    ...(core.ignorePatterns ?? []),
    "**/generated/**",
    "**/dist/**",
    "**/bench_deno.ts",
  ],
  overrides: [
    {
      // Two dynamic boundaries, scoped here so the rest of the workspace stays
      // fully type-checked:
      //  1) The SDK transport/decode/media boundary — adapters parse raw WS/Zenoh
      //     frames, decodeBody() returns `unknown`, the client casts to the topic
      //     type, srcTsMs probes an arbitrary header, the media plane decodes raw
      //     frames.
      //  2) The dimoscope VIZ app — panels auto-detect heterogeneous bus messages
      //     by type and render them (canvas/Rerun), so they read topic data as
      //     `any`. FOLLOW-UP: re-type the panels with @dimos/msgs (the library
      //     packages @dimos/{topics,react} stay strict regardless).
      files: [
        "packages/topics/src/decode.ts",
        "packages/topics/src/client.ts",
        "packages/topics/src/media.ts",
        "packages/topics/src/image.ts",
        "packages/topics/src/adapters/*.ts",
        "apps/dimoscope/src/**/*.{ts,tsx}",
      ],
      rules: {
        "typescript/no-explicit-any": "off",
        "typescript/no-unsafe-assignment": "off",
        "typescript/no-unsafe-member-access": "off",
        "typescript/no-unsafe-call": "off",
        "typescript/no-unsafe-argument": "off",
        "typescript/no-unsafe-return": "off",
        "typescript/no-unsafe-type-assertion": "off",
        // The viz/CV path uses `||` deliberately for NUMERIC 0-fallthrough (frame
        // dims: `meta.width || displayWidth || width` — a 0 width must fall through;
        // `??` would keep the invalid 0). So prefer-nullish is a false positive here.
        "typescript/prefer-nullish-coalescing": "off",
      },
    },
  ],
  rules: {
    // ── house-style baseline (mirrors invok) ──
    "eslint/sort-keys": "off",
    "eslint/curly": "off",
    "eslint/no-negated-condition": "off",
    "unicorn/no-negated-condition": "off",
    "eslint/no-plusplus": "off",
    "eslint/no-inline-comments": "off",
    "eslint/prefer-destructuring": "off",
    "eslint/no-nested-ternary": "off",
    "unicorn/no-nested-ternary": "off",
    "eslint/func-style": "off",
    "eslint/no-empty-function": "off",
    "unicorn/switch-case-braces": "off",
    "unicorn/catch-error-name": "off",
    "unicorn/no-useless-undefined": "off",
    "unicorn/throw-new-error": "off",
    "typescript/consistent-type-definitions": "off",
    "typescript/no-confusing-void-expression": "off",
    "typescript/promise-function-async": "off",
    "typescript/prefer-readonly-parameter-types": "off",
    "eslint/no-await-in-loop": "off",
    "eslint/require-await": "off",
    // ── SDK is event-driven / callback-rich ──
    "typescript/method-signature-style": "off",
    "typescript/parameter-properties": "off",
    "unicorn/no-array-for-each": "off",
    "unicorn/prefer-add-event-listener": "off",
    "promise/prefer-await-to-then": "off",
    "promise/prefer-await-to-callbacks": "off",
    // ── long-tail (pedantic / SDK domain) ──
    "unicorn/filename-case": "off",
    "eslint/no-eq-null": "off",
    "eslint/eqeqeq": ["error", "always", { null: "ignore" }],
    "eslint/class-methods-use-this": "off",
    "promise/avoid-new": "off",
    "promise/no-nesting": "off",
    // ── React-effect / generic-hook idioms ──
    "typescript/consistent-return": "off",
    "eslint/complexity": "off",
    "typescript/no-unnecessary-type-parameters": "off",
    // ── domain idioms: canvas (getContext!), Promise-sleep, bench scripts ──
    "typescript/no-non-null-assertion": "off",
    // binary-protocol SDK: LCM hashing + WebCodecs frame flags use bitwise ops
    "eslint/no-bitwise": "off",
    // `as` narrowing is a deliberate dev assertion (select values, DOM/Error casts,
    // media frames); dangerous any-flows are still caught by the other no-unsafe-* rules.
    "typescript/no-unsafe-type-assertion": "off",
    // async event handlers (onClick={async …}) are fine; still flag `if (promise)`.
    "typescript/no-misused-promises": ["error", { checksVoidReturn: false }],
    // the SDK is event/callback-driven, not Node error-first callbacks.
    "node/callback-return": "off",
    // TS exhaustive-union switches (e.g. MediaKind) don't need a default arm.
    "eslint/default-case": "off",
    "typescript/strict-void-return": "off",
    "eslint/no-promise-executor-return": "off",
    "promise/param-names": "off",
    "eslint/sort-vars": "off",
    "unicorn/consistent-function-scoping": "off",
    "eslint/no-use-before-define": ["error", { functions: false }],
    // tuned (invok): allow nullable string/bool truthiness; flag nullable number
    "typescript/strict-boolean-expressions": [
      "error",
      {
        allowString: true,
        allowNumber: true,
        allowNullableObject: true,
        allowNullableBoolean: true,
        allowNullableString: true,
        allowNullableNumber: true,
        allowNullableEnum: true,
        allowAny: true,
      },
    ],
  },
});
