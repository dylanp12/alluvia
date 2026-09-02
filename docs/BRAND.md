# alluvia — brand guide

**The mark:** three tributaries converge at a gold node and continue as one
stem. It diagrams the product (many scattered threads, settled down to one
find) and doubles as a quiet nod to a merge graph. The name is written
`alluvia`, lowercase always, exactly as typed: `pip install alluvia`.

The design language is **the record**: a printed document on paper, set with
the care of a filing that expects to be checked. Every claim carries its
citation; evidence is entered, not announced. Warm paper ground, ink for
everything that speaks, hairlines for structure, and gold reserved for the one
thing that matters: a deposit was found. Keep it rigorous, not romantic. Every
mark should carry information, never decoration.

## Palette — paper, ink, and the deposit

| Token | Hex | Role |
|---|---|---|
| Paper | `#F5F1E8` | the ground |
| Sheet | `#FBF8F1` | raised surfaces: cards, exhibits, the answer card |
| Wash | `#EFE4C9` | gold's tint: receipts, hover, selection |
| Ink | `#201D18` | primary text, strokes, buttons |
| Ink-soft | `#3A362D` | secondary emphasis |
| Silt | `#6F6759` | secondary text on paper |
| Faint | `#948B7A` | rules and decoration only, never text |
| Line / Line-strong | `#DFD8CA` / `#C4BBA6` | hairlines / structural rules |
| Gold | `#9A6B15` | **the deposit**: fills, strokes, nodes, pill borders |
| Gold-text | `#845B11` | gold when it must be read as text |

**Contrast is measured, not eyeballed** (WCAG, against the ground it renders
on): Ink on Paper 14.9:1 · Silt on Paper 4.95:1 · Gold-text on Paper 5.34:1,
on Sheet 5.68:1, on Wash 4.77:1 · Paper on Ink (buttons) 14.9:1. Two numbers
set hard rules: **Gold on Paper is 4.15:1** (fine as a mark, fails as small
text: use Gold-text) and **Faint on Paper is 2.99:1** (never text).

### Rule 01 — gold means a deposit was found
Gold marks exactly one thing: something true was found in the record. The
citation mark, the receipt index, the confidence pill, the verified check, the
confluence node, the bridge between two sessions. States where nothing was
found carry **zero gold**: the honest refusal ("no record of that"), the
privacy rows that say *nowhere*. Buttons are ink. Read the rule semantically,
not by count: in a list, only the found or verified row golds. Scarcity is what
makes gold read as value.

### Rule 02 — gold as text uses Gold-text; Faint is never text
- **Gold as a mark** (`#9A6B15`): fills, strokes, nodes, borders, the pill
  outline. Not for running text on light grounds.
- **Gold as text** (`#845B11`): citation superscripts, receipt indices,
  `cites [1] [2]`, source numbers. Passes AA on Paper, Sheet, and Wash, so it
  survives hover and selection tints.
- **Silt** is the secondary text color on Paper. **Faint** is for hairline
  numbers, stream labels, and rules only.
- Ink on the Wash tint is fine (13.3:1). Silt on Wash is 4.42:1, so raise
  hovered secondary text to Ink-soft.

### Rule 03 — status colours ship with a label
Theme status is a fixed scale, never color alone (WCAG 1.4.1): always a
colored dot **plus** the text label. Values clear 3:1 on Paper.

| Status | On Paper | reads as |
|---|---|---|
| open | `#B5533B` | warm: needs attention |
| resolved | `#2E7D6F` | cool: done |
| dormant | `#6E7C87` | quiet slate |
| unknown | `#8A8072` | quiet taupe |

`open`/`resolved` separate by hue (warm/cool); `dormant`/`unknown` by
lightness. All four sit well below Gold's chroma, so the single gold find still
carries the eye. Source series in charts use a small legend-led categorical set
(blue `#2E6E9E` · rust `#C0562A` · teal `#1E8C79`; further sources fold into a
neutral "other").

## Type

- **Newsreader** (variable, optical sizes): headlines and the two italic
  moments, the refusal line and the found utterance. A text serif, because this
  is a record and records are set in text serifs; modern enough to sit beside
  a terminal. OFL.
- **Geist**: body and interface. Quiet and dense, like a well-set filing. OFL.
- **JetBrains Mono**: doing real work only. Citations, receipts, timestamps,
  session slugs, table values, code. Never decoration. OFL.

All three are self-hosted wherever they appear; nothing loads from a font CDN.
The localhost dashboard keeps its zero-external-request rule and falls back to
system faces when a family is absent.

## Motion — evidence gets entered

Documents do not animate; evidence gets entered. Text never flies. Reveals are
opacity plus a few pixels of rise, once, on first sight. The only drawn motion
is a stream drawing itself into the confluence node, or a receipt row entering
the record. Everything respects `prefers-reduced-motion`, and a page with
scripts disabled reads as the finished record.

## Voice — stay in the river, cite the record

The metaphor stays **placer-fluvial** (settling gold out of river sediment);
the register is **the record** (receipts, citations, an honest no record).

- **Whitelist:** settle, converge, trace, survey, follow upstream, read the
  current, the confluence, the find, the record, the receipt, cited.
- **Deny-list:** no hard-rock mining imagery or verbs: no pickaxe, shaft, vein,
  ore, and never *mine, dig, unearth, excavate*. One image of a mineshaft snaps
  the brand into an incoherent river-vs-mining split.
- Ration the word **gold** the way the visuals ration the color: at most once
  per composition, and never in a headline sitting beside a gold visual.
  Prefer *the find*, *the confluence*, *what settled*.
- Lead with the moat: **local-first · MIT · zero telemetry · your data never
  leaves your machine.** Keep DeFi-adjacent nouns (token, asset, ledger, vault)
  out of product and UI naming.
- Claims come with receipts. A number appears only if it is real and traceable;
  the honest "no record" is a feature, so say it plainly and never dress it up.
- Punctuation on product surfaces and docs: periods, colons, commas, and
  parentheses. No em dashes.

## README header (dark/light aware)

```html
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/alluvia-lockup-dark.svg">
    <img src="assets/alluvia-lockup.svg" alt="alluvia" width="420">
  </picture>
</p>
<p align="center"><em>Pan your AI history for gold.</em></p>
```

## CLI color

Truecolor gold `\x1b[38;2;154;107;21m` (256-color fallback: `136`). Reserve it
for exactly one thing per view: the bridge/connection glyph. Everything else
default or dim.

## Assets & rollout

`assets/` holds the kit: `alluvia-lockup(.svg/-dark.svg)`, `alluvia-mark-wide`,
`alluvia-mark-square`, `alluvia-favicon.svg`, `favicon-32.png`,
`alluvia-social-preview.png` (1280×640), and `alluvia-tokens.css` (the token
source of truth). The installed wheel ships only the package, not `assets/`.

1. **Social preview**: repo Settings → General → Social preview → upload
   `alluvia-social-preview.png`. Highest-leverage single change: it is what
   every shared link renders.
2. Header lockup pair + `<picture>` snippet above; badges use color `9A6B15`.
3. The localhost dashboard (`alluvia serve`) still inlines the previous
   sediment palette and IBM Plex Mono; it migrates in a later release. Until
   then the dashboard is the one surface that predates this guide.

Fonts: <https://fonts.google.com/specimen/Newsreader> ·
<https://vercel.com/font> (Geist) ·
<https://www.jetbrains.com/lp/mono/> (all OFL, safe to commit).
