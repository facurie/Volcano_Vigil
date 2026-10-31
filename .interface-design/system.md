# Volcano Vigil: interface design system

The dashboard (`vigil/web/static/`) was built in Phase 6, on 2026-10-30. Every new screen or component holds to the decisions below. The values live in `vigil/web/static/css/app.css` (`:root`). This file says why they are what they are.

## Direction

- **Who:** a hackathon judge, or someone on the Big Island checking the summit, with a few minutes and one link. They must *see the agent watch the eruption and get it right*. The author records the demo video from the episode 55 replay.
- **Feel:** an observatory's night shift. It is dark like the summit at 04:00 when the fountain lights the plume, and calm and exact like a survey instrument. It is not a SaaS dashboard.
- **Dark only.** The cameras are watched through the night, and incandescence reads on black. There is no light theme.
- **Never imitate an alert level.** Use no green, yellow or red status scheme. A state is a word plus, at most, the colour of what is visible: plume, fountain or glow. The notice "Not an official alert", with the link to HVO, is in every page's own markup and stays sticky with the top bar.

## Signatures

Keep these; they make the product recognisable.

1. **The drum.** Height over time is a helicorder drum on the episode's time axis.
   - It inks only up to the clock and leaves the future as blank paper (`--well`).
   - HVO's values appear only once HVO had given them.
   - Per-camera frame strips sit under it on the same axis.
2. **The line of sight.** On the map, a camera's position is drawn as a circle of its σ, with its sightline to the vent.
   - The plume's measured side is drawn *across* that sightline, with length `|drift_offset|` towards `drift_bearing`. One camera sees only that component of the drift.
   - The layer-mean wind is drawn beside it, at 600 m per m/s.
3. **± σ on every number.** The uncertainty sits next to the value, in a quieter weight or ink: `6,964 m` with `± 419 m · 22,848 ft`.

## Tokens

| Token | Value | Role |
|---|---|---|
| `--basalt` | `#100e0d` | the page: fresh lava's warm black |
| `--basalt-1` | `#161311` | panels |
| `--basalt-2` | `#1d1916` | raised: active control, tooltips |
| `--well` | `#0a0908` | insets: the frame, inputs, the drum's future |
| `--notice` | `#1f1a11` | the notice strip (sulphur on basalt) |
| `--rule` / `--rule-strong` | `rgba(236,226,212,.08)` / `.14` | hairlines |
| `--steam` | `#ede4d6` | primary ink |
| `--ash` | `#b4aa9c` | secondary ink |
| `--tephra` | `#8d8377` | labels, metadata (≥ 4.5:1 on panels) |
| `--cinder` | `#5a524a` | disabled, rejected frames |
| `--lava` | `#f25820` | **the only accent**: the clock, focus ring, play button; also the fountain on dark surfaces |
| `--plume` | `#259ed6` | plume on dark surfaces |
| `--glow` | `#b68c00` | glowing lava on dark surfaces (level dot only) |
| `--lehua` | `#c3518d` | HVO's official values; ʻōhiʻa lehua, the first plant on new lava |
| `--mask-plume` / `--mask-fountain` / `--mask-glow` | `#50c8ff` / `#ff5a1e` / `#ffd200` | the colours the masks are drawn in on frames (`vigil.agent.bulletin.COLORS`); use them only to key those masks |
| `--sulfur` | `#d8b04a` | the notice tag and the bulletin disclaimer rule; nothing else |

There are scrim and edge tokens for overlays: `--bar-scrim`, `--map-scrim`, `--hover`, `--photo-edge` and `--notice-rule`. No hex or `rgba()` may appear outside `:root`.

### Chart colours

These were validated with the dataviz palette checks, on the panel `#161311` in dark mode across all pairs: plume `#259ed6`, HVO `#c3518d` and fountain `#f25820` pass the lightness band 0.48–0.67, the chroma floor, CVD (worst ΔE 11.0, deutan) and normal vision (worst 16.2).
- **Rejected:** the overlay colours, which are too light at L 0.79 and 0.88.
- **Rejected:** a neutral for HVO, which fails the chroma floor.
- **Rejected:** olivine green or violet for HVO, which fail deutan against lava or plume.
- **Glow never shares a chart with the fountain**, because their deutan ΔE is 0.6.
- **Before adding a hue, re-run the validator.**

## Type

- **IBM Plex Sans:** body, 14/1.5.
- **IBM Plex Sans Condensed:** labels and panel titles, 11–13px, weight 600, uppercase, letter-spacing .08em, in `--tephra` or `--ash`.
- **IBM Plex Mono:** every time and number, with tabular figures.
- **Hierarchy comes from weight and ink before size.** Scale ≈ 1.2: 11, 12, 13, 14, 15, 20, 22. The one exception is the hero.
- **One hero figure per view:** the plume top, in Plex Sans 48px, weight 600, letter-spacing −.02em (40px on phones). Its unit is 20px in `--ash`, and its σ line is mono 14px.
- **Text never takes a data colour.** A key (line, dot or diamond) next to the text carries the identity.

## Depth, spacing, shape

- **Borders only:** 1px `--rule` hairlines, and no shadows. Surface steps are a few points of lightness: basalt → basalt-1 → basalt-2.
- **Base unit 4px:** `--s1` 4 · `--s2` 8 · `--s3` 12 · `--s4` 16 · `--s5` 24 · `--s6` 32. Panels use 16px padding and 16px gaps.
- **Radius:** `--r-sm` 4px for controls, `--r-md` 6px for panels.
- **Motion:** under 200ms with `--ease: cubic-bezier(.23,1,.32,1)`. Animate only opacity and transform, and press feedback is `scale(.97)`. Honour `prefers-reduced-motion`.

## Layout

- **Desktop:** `grid-template-columns: minmax(0,1fr) 400px`, max-width 1680px, with the areas `"viewer feed" "drum map" "trace trace"`.
  - The frame (viewer) is the focal element.
  - The feed sits beside it at the frame's height and scrolls inside: the inner panel is absolutely positioned so it never sets the row's height.
- **Under 1180px:** one column, in the order viewer, feed, drum, map, trace.
- **Under 640px:** the top bar wraps, and the clock takes its own row.
- **Top bar and notice:** sticky together at the top.
- **Replay transport:** sticky at the bottom, with a `--bar-scrim` background.

## Component patterns

- **Segmented control** (`.modes`, `.seg`): a `--well` track with 2px padding. Buttons are 32px tall with 6×12px padding. The pressed one is `--basalt-2` with a ring of `--rule-strong`. Use `aria-pressed`.
- **Panel head:** at least 48px tall, padded 8×16px. The title is condensed 13px, weight 600, uppercase, in `--ash`. Extras sit on the right (`.aside`).
- **Camera tab:** at least 44px tall. A condition dot (8px; filled steam when usable, hollow cinder otherwise) sits before the short name and the condition word in mono 12px. The selected tab has a 2px `--lava` bottom border.
- **Icon button:** 40×40, `--basalt-2`, with a hairline border. Play is the one filled `--lava` button.
- **Level chip:** an 8px dot coloured by what is visible (fountaining = lava, incandescence = glow, degassing = plume, quiet = ash, no_view = hollow) before a condensed uppercase word. It is never an alert level.
- **Bulletin measurements in a narrow column:** a two-line list per row. The first line holds the "what" in ink and the value in mono steam on the right. The second line holds the camera, frames, capture time and checked status in mono 11.5px tephra. A six-column table does not fit 400px.
- **Tooltip:** `--basalt-2` with a `--rule-strong` hairline and mono 12px. The value leads, in `<strong>` steam, and the context follows in ash.
- **Drum:**
  - margins: left 48, right 16, top 20, bottom 24;
  - the plot is 300px tall when the panel is at least 700px wide, else 200px;
  - y axis: 0 to at least 9 km, with gridlines every 2 km;
  - one 16px strip row per camera;
  - the line is broken at gaps over 30 min, and a lone point is a dot with a σ bar;
  - HVO values are 10px lehua diamonds with a 2px panel ring, and an upper bound gets a downward tick;
  - phases are steam hairlines at 35 %, and the peak a 5 % band;
  - the clock is a 1.5px lava line;
  - x-axis ticks at local midnight carry the date.
- **Map:** USGS The National Map imagery, dimmed with `saturate(.55) brightness(.62) contrast(1.05)`; the map is 300px tall with `isolation: isolate`. Leaflet tooltips are always DOM nodes, never strings, because Leaflet reads strings as HTML.

## Rules that are also correctness

- **Model text only as text.** It reaches the DOM through `el()` or `fill()` in `js/dom.js`. `tests/test_web_static.py` forbids `innerHTML`, `outerHTML`, `insertAdjacentHTML` and `document.write`.
- **Times use the volcano's offset, never the browser's zone.** They go through `lib.localTime`, `lib.stamp` or `lib.localDate`, with `config.volcano.utc_offset_hours`.
  - A time on another local day than the clock carries its date (`lib.stamp`).
  - Show a zone label next to times: `UTC−10`, or `UTC`.
- **Numbers print as the English bulletins print them:** `lib.number` and `lib.plusMinus`, with areas in km².
- **Show only what the API sent for the scene's clock.** Image URLs use the clock the API answered with, and a superseded load must never paint.
