# DealScope design system - "Editorial research memo"

Reads like a diligence report (FT / Economist research note): warm paper, ink, hairline rules, serif headlines and numerals. Structure comes from rules and whitespace, not boxes or shadows.

## Flow
- **Search-first Home** (`pages/Home.tsx`): one company-website box and one button. Live searches run a free identity check first, then start. Competitors, thesis, look-back (3-36 months) and credit limit sit under "Refine". Demo data is an opt-in toggle that prefills a made-up scenario; leaving demo clears those values.
- **Answer card** (`components/AnswerCard.tsx`): the first thing on a case page. While running: one calm progress line ("Step n - current step - elapsed time") over a skeleton, with no invented totals. When done: headline, verdict pill (neutral "Not enough evidence" when there is no level), score, a plain coverage note, up to three questions to ask management, then one next step. Setup hints (keys, config) show as a quiet note instead of the call to action.
- **Full report** is a collapsed disclosure below the card; it opens automatically for section deep links such as `/cases/x#evidence`.

## Files
- `src/styles/tokens.css` - all custom properties + dark mode. Never hardcode colors/sizes elsewhere.
- `src/styles/base.css` - reset, typography, links, tables, forms, buttons, masthead/footer, styles for `ui.tsx` primitives.
- `src/styles/start.css` (search Home, recent searches, Cases history), `case.css` (case detail + components), `pages.css` (Compare, Evidence, How it works) - page-owned, seeded from legacy rules.
- `global.css` only `@import`s them in order. Page CSS goes in the matching page file.

## Tokens
- Surfaces/ink: `--bg` paper, `--ink`, `--ink-2` (secondary text), `--muted` (meta, AA), `--line` (hairline), `--line-strong` (input borders), `--rule` (heavy ink rule), `--surface` (inputs/popovers only), `--surface-2` (faint wash).
- Accent (deep teal, sparingly: links, focus, active nav, key emphasis): `--accent`, `--accent-ink`, `--accent-soft`, `--focus`.
- Tones `good|neutral|caution|bad|info`: `--{tone}-fg` (text), `--{tone}-bar` (marker/rule/fill), `--{tone}-bg` (faint wash, use rarely). Apply `.tone-{tone}` to set `--tone-fg/--tone-bar/--tone-bg` then consume them.
- Fonts: `--font-serif` (Source Serif 4: headlines, big numbers, ledes), `--font-sans` (Inter: UI/body), `--font-mono` (IBM Plex Mono: ids, code). Legacy aliases `--font`, `--mono`.
- Type scale: `--fs-2xs` 11 (kicker/th), `--fs-xs` 12.5, `--fs-sm` 14, `--fs-base` 15.5 (body), `--fs-md` 17 (lede), `--fs-lg` 20 (h3), `--fs-xl` 26 (h2), `--fs-2xl` 34 (h1), `--fs-display` 56 (hero numbers). Line heights `--lh-tight` 1.15, `--lh-snug` 1.3, `--lh-body` 1.6. `--track-kicker` 0.12em.
- Spacing: `--space-1..8` = 4, 8, 12, 16, 24, 36, 56, 80 px.
- Layout: `--max-w` 1120px (`.main`), `--measure` 68ch (prose; `.dek`), `--gutter` 16px, `--radius` 3px, `--hair` 1px, `--heavy` 2px.

## Primitives (`components/ui.tsx`)
| Component | Use |
|---|---|
| `PageHeader {kicker,title,dek}` | Top of every page: accent kicker, serif h1, serif dek |
| `SectionHead {id,title,subtitle}` | Every major section; 2px ink rule above |
| `Kicker {accent}` | Small-caps eyebrow over titles/numbers |
| `Rule {heavy}` | Hairline or 2px ink divider |
| `Dateline {items}` | Byline-style meta row (date / mode / source) |
| `Stat {value,label,unit,note,tone,size}` + `StatGrid` | Serif numerals with small-caps label; `size="lg"` for hero figures |
| `StatusPill {tone}` | Tone text + square marker (not a filled pill) |
| `ModeBadge` | Outlined badge: synthetic demo vs live |
| `Banner {tone,title}` | Left-rule note; warnings/errors in flow |
| `Meter` | 4px square bar + serif value |
| `Disclosure` | Hairline-ruled details/summary |
| `Loading`, `ErrorBox`, `EmptyBox`, `CopyButton`, `Icon` | States and utilities |

## CSS classes available
Layout `.main .section .grid-2 .cols-2 .btn-row .dek .muted .small .num`; `.btn` (`.primary`, `.small`); forms `.field .input .textarea .select .help .error-text .check .chips .chip`; `.tabs .tab`; tables use plain `<table>` inside `.table-wrap` (`td.num/th.num` right-aligned); tones `.tone-*`, `.pos`, `.neg`.

## Do
- Hierarchy through size, weight, serif vs sans, and rules. One focal element per section.
- Numbers (scores, costs, counts) in serif with tabular lining figures (`Stat`, `.num`).
- Express status by colored text + square marker or a 2-3px left rule.
- Use kicker labels for section eyebrows; keep prose within `--measure`.
- Keep layouts working at 375px with no horizontal scroll; wrap wide tables in `.table-wrap`.

## Don't
- No box-shadows, glows, gradients, filled saturated pills, or boxes around everything.
- No radius above 4px; no zebra tables; no hardcoded hex colors (use tokens, dark mode depends on it).
- Don't use accent for status (teal is brand only; red/amber/green are status).
- Don't add animations beyond subtle transitions; reduced motion is respected globally.

## Migration notes for page agents
- `.stat` is now flat (top hairline, serif value); `.stat-grid` unchanged.
- `.pill`, `.badge`, `.banner`, `.thesis`, `.finding`, `.signal`, `.tw-*` were restyled to flat/ruled looks but keep their class names; restructure markup freely.
- Removed: `.topbar`, `.topbar-inner` (now `.masthead*`), `--navy`, `--shadow`, `--navy-ink`. `--radius` is 3px.
- Page CSS owners: start.css, case.css, pages.css. Do not edit base.css/tokens.css; request changes instead.
