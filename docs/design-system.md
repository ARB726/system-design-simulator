# Systems Lab interface direction

The interface is an engineering workbench. The primary task is to configure a system, run an experiment, inspect the evidence and compare one controlled change.

- **Paper and ink:** warm neutral surfaces, dark green navigation, restrained orange actions. Borders and spacing establish hierarchy; glow and glass effects do not.
- **Typography:** local system fonts for controls, a serif for the main question and outcome, and monospace for measurements. Essential inputs use 16px text. Primary actions are at least 44px tall.
- **One model:** the request-path schematic is the architecture canvas. Selecting a tier exposes its real configuration; optional-layer controls update the same model as the parameter fields.
- **Purposeful motion:** animation follows configured request paths. It can be paused and honours reduced-motion preferences. There is no page-wide particle animation or invented activity trace.
- **Evidence first:** state the question and conditions, then the observed tradeoff, measurements and charts. Performance regressions and added cost have distinct meanings. Mismatched experiment conditions are explicit.
- **Responsive navigation:** the experiment steps remain available while scrolling. Configure links to editable parameters so mobile visitors can skip the model overview.
- **Honest provenance:** samples are identified as recorded simulations; model inputs are not described as measured results. Shared snapshots remain read-only and unverified.

The visual foundation lives in `fullstack/frontend/app/workbench.css`; schematic layout lives in `topology.css`. Existing layout primitives remain in `globals.css`.

Run the browser suite after changes. It covers control sizing and contrast, 320–1440px overflow, inspection and model updates, mobile navigation, pause/reduced motion, comparison regressions, authentication, sharing, media playback and the simulation workflow. Review desktop, mobile, guest and result screenshots as well as test output.
