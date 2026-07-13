# alluvia — brand guide

**The mark:** three tributaries converge at a gold node and continue as one
stem. It diagrams the product — many scattered threads, panned down to one find
— and doubles as a quiet nod to a merge graph. The name is written `alluvia`,
lowercase always, exactly as typed: `pip install alluvia`.

The design language is the **patient field survey**: fluvial cartography drawn
by hand, measured by instrument. Warm mineral ground, few exact marks, and one
scarce point of gold. Keep it rigorous, not romantic — every mark should carry
information, never decoration.

## Palette — sediment & gold

| Token | Hex | Role |
|---|---|---|
| Ink | `#1C2B33` | line, primary text |
| Basin | `#131F26` | dark surfaces |
| Paper | `#F4EFE6` | light ground |
| Wash | `#E9E2D4` | light cards / hover |
| Silt | `#A89F91` | rules; secondary text **on dark only** |
| Silt-ink | `#6F675B` | readable secondary text **on light** (Paper 4.9:1) |
| Gold | `#D4A017` | **the find** — a filled mark, used once |

**Contrast is measured, not eyeballed** (WCAG, against the ground it renders on):
Ink on Paper 12.7:1 · Paper on Basin 14.7:1 · Ink on Gold 6.1:1 · Gold on Basin
7.1:1. Two numbers set hard rules below: **Silt on Paper is 2.3:1** and **Gold on
Paper is 2.1:1** — both fail as text.

### Rule 01 — gold is scarce, and it is a *mark*
Gold marks **the find**: the confluence node, the bridge/rediscovery, the kept
proposal, the one active/selected element. Read it semantically, not by count —
in a list, only the found or selected row golds; in a hero, the single
confluence. Never gold headings, gold chrome, gold borders, or gold everywhere.
Scarcity is what makes it read as value.

### Rule 02 — gold and silt are ground-scoped
- **Gold on light (Paper/Wash):** a **filled shape only** — a gold fill with Ink
  text/icon on it. Never gold text, links, or strokes on light (2.1:1 is
  unreadable). Gold-as-text is allowed **only on Basin/Ink** (7.1:1).
- **Silt on light:** rules and dividers only — **never text**. For readable
  secondary text on Paper use **Silt-ink `#6F675B`**. Silt is a valid
  secondary-text colour only on Basin (6.4:1).
- Never place Ink text on Basin (1.2:1 — they merge).

### Rule 03 — status colours ship with a label
Theme status is a fixed scale, never color alone (WCAG 1.4.1) — always a colored
dot **plus** the text label. Values clear ≥3:1 on both grounds; each hue lightens
one step for the dark ground.

| Status | Light (on Paper) | Dark (on Basin) | reads as |
|---|---|---|---|
| open | `#B5533B` | `#D07A5E` | warm — needs attention |
| resolved | `#2E7D6F` | `#46A08F` | cool — done |
| dormant | `#6E7C87` | `#8D9BA6` | quiet slate |
| unknown | `#8A8072` | `#B4A992` | quiet taupe |

`open`/`resolved` separate by hue (warm/cool); `dormant`/`unknown` by lightness.
All four sit well below Gold's chroma, so the single gold find still carries the
eye. Source series in charts use a small legend-led categorical set
(blue `#2E6E9E` · rust `#C0562A` · teal `#1E8C79`; further sources fold into a
neutral “other”).

## Type

- **National Park Bold** — wordmark and display. Trail-signage lettering; OFL.
  It can read outdoorsy/craft — that's a deliberate keep, not an oversight: the
  tech-enthusiast and outdoors audiences overlap heavily, and the tactile,
  owned, field-survey feel reinforces the local-first / own-your-data thesis
  rather than fighting it.
- **IBM Plex Mono** — annotations, labels, station readouts, code; OFL. Let the
  mono do real work — it reads as *field instrument*, which is the point.
- System sans for body text. No webfont needed for docs, and the localhost
  dashboard ships zero external requests: it embeds the wordmark as vector paths
  and falls back to `ui-monospace` when Plex Mono is absent.

## Voice — stay in the river

The whole system coheres only while it stays **placer-fluvial** (panning gold from
river sediment). Keep the metaphor there.

- **Whitelist:** pan, settle, converge, trace, survey, follow upstream, read the
  current, the confluence, the find.
- **Deny-list:** no hard-rock mining imagery or verbs — no pickaxe/shaft/vein/ore,
  and never *mine / dig / unearth / excavate*. One image of a mineshaft snaps the
  brand into an incoherent river-vs-mining split.
- Ration the word **gold** the way the visuals ration the color: at most once per
  composition, and never in a headline sitting beside a gold visual. Prefer *the
  find*, *the confluence*, *what settled*.
- Lead with the moat: **local-first · MIT · zero telemetry · your data never
  leaves your machine.** Keep DeFi-adjacent nouns (token, asset, ledger, vault)
  out of product and UI naming.

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

Truecolor gold `\x1b[38;2;212;160;23m` (256-color fallback: `178`). Reserve it
for exactly one thing per view: the bridge/connection glyph. Everything else
default or dim.

## Assets & rollout

`assets/` holds the kit: `alluvia-lockup(.svg/-dark.svg)`, `alluvia-mark-wide`,
`alluvia-mark-square`, `alluvia-favicon.svg`, `favicon-32.png`,
`alluvia-social-preview.png`, and `alluvia-tokens.css` (the token source of
truth). The dashboard inlines its own favicon and tokens — the installed wheel
ships only the package, not `assets/`.

1. **Social preview** — repo Settings → General → Social preview → upload
   `alluvia-social-preview.png`. Highest-leverage single change: it is what every
   shared link renders.
2. Header lockup pair + `<picture>` snippet above; keep the `d4a017` badge color.
3. Favicon + tokens live inline in the dashboard (`alluvia serve`).

Fonts: <https://fonts.google.com/specimen/IBM+Plex+Mono> · National Park:
<https://nationalparktypeface.com> (both OFL — safe to commit).
