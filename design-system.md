# TimeLens interface system

## Direction

TimeLens is an evidence workbench, not a generic dashboard. The interface borrows from an illuminated radiology reading desk: near-black film surfaces, restrained sea-glass teal, amber only for review-worthy disagreement, and generous editorial typography.

## Information hierarchy

1. Plain-language conclusion.
2. Earlier-to-current visual transition.
3. Image/report agreement for each study.
4. Expandable clinical evidence.
5. Expandable OpenSwarm execution trace.

Raw model vocabulary such as `absent_both` must never be the primary user-facing conclusion. Technical image language belongs behind an evidence disclosure.

## Interaction

- Analysis progress must reflect persisted backend states; never show fabricated percentages or fake agent activity.
- Image controls provide button alternatives for zoom/reset and pointer dragging is an optional enhancement only.
- All controls are at least 44px, keyboard reachable, visibly focused and named for assistive technology.
- Status always combines text, shape and color.
- Motion uses transforms and opacity, communicates state change and is disabled under `prefers-reduced-motion`.

## Visual tokens

- Background: `#0b1112`; film: `#050809`.
- Primary text: `#f1f6f3`; muted text: `#869795`.
- Active/evidence: `#9de4ce`; human review: `#ffc36e`; success: `#9ee6bd`; failure: `#ff9f96`.
- Body/interface: local Avenir Next stack. Editorial conclusions: local Iowan Old Style stack.
- Corners: 11px controls, 14px cards, 18px primary panels.

No third-party fonts, scripts, medical overlays, generated heatmaps, confidence scores or decorative health metrics.
