# Career CoDesk UI redesign — design QA

## Result

**final result: passed**

The implementation preserves the selected combined direction: a dark navy adviser shell, a
synthetic-data boundary banner, cobalt and violet evidence separation, a compact capacity band,
and a bottom decision bar. All existing product routes use the same visual system.

## Comparison evidence

- Selected design target and implementation comparison: .design-qa/comparison-review.png
- Final implementation state: .design-qa/09-review-final.png
- Same-input side-by-side comparison: .design-qa/comparison-review-final.png
- Desktop browser viewport: 1493 × 963 CSS pixels, device pixel ratio 2.
- Mobile verification frame: 390 × 844 CSS pixels; rendered document width 375 CSS pixels.
- State compared: ordinary guide proposal, not active, with one source capture, one provisional
  inference, persisted capacity evidence, one feasible alternative, and the adviser decision
  controls visible.

The target and final implementation were normalized into one 1440 × 512 comparison canvas.
The final implementation matches the target's hierarchy, two-column evidence model, semantic
palette, restrained radii and shadows, compact capacity summary, and decision-first workflow.
Dynamic fixture content is shorter than the illustrative target, so the implementation is
intentionally less vertically dense without inventing source evidence.

## Page coverage

- .design-qa/01-queue.png — decision queue
- .design-qa/09-review-final.png — evidence review and decision bar
- .design-qa/03-confirm.png — immutable decision confirmation
- .design-qa/08-decision-result.png — decision result and replanning summary
- .design-qa/04-plans.png — approved weekly plans
- .design-qa/05-plan-detail.png — execution package and local export
- .design-qa/06-learner.png — approved learner action and four feedback paths
- .design-qa/07-feedback-recorded.png — learner feedback confirmation
- .design-qa/10-review-mobile-390x844.png — mobile review layout

## Fidelity review

- **Typography:** Passed. The implementation uses the local system sans stack because no bundled
  brand font exists and remote downloads are paused. Weight, line height, uppercase metadata, and
  headline scale reproduce the target's hierarchy without a network dependency.
- **Spacing and layout:** Passed. Desktop content uses a fixed navigation rail, a wide evidence
  workspace, paired source/inference panels, a five-part capacity band, and a compact sticky
  decision bar. Cards use 7–10 px radii, 1 px borders, and restrained elevation.
- **Colour and surfaces:** Passed. Navy, warm paper, cobalt, violet, emerald, and amber tokens map
  to navigation, evidence, approval, capacity, uncertainty, and boundary states. No gradients or
  decorative imagery were introduced.
- **Copy and data:** Passed. All visible records come from existing synthetic fixtures. Source
  evidence, provisional interpretation, deterministic rationale, and human decisions remain
  visually and semantically separate.
- **Icons and imagery:** Passed for scope. The selected direction uses only small decorative
  utility icons. The repository has no bundled icon family and remote dependency installation is
  prohibited, so the implementation uses labelled controls instead of fake SVG, CSS art, emoji,
  or mismatched glyphs. No product imagery is required.
- **Responsive layout:** Passed. At a 375 px rendered width, document scroll width equals client
  width, the two-column evidence and decision layouts collapse to one column, navigation becomes
  horizontally scrollable, and all decision buttons measure 313 × 44 px.
- **Accessibility smoke checks:** Passed. Semantic headings, tables, labels, skip-link, visible keyboard focus,
  reduced-motion handling, 44 px mobile actions, status text independent of colour, and text
  wrapping are present.

## Interaction and error checks

- Queue sorting and queue-to-review navigation loaded successfully.
- Approve was exercised through the reason field to the confirmation page without recording.
- Reject was exercised through confirmation to the decision result in the isolated QA database.
- Weekly-plan list navigation opened an execution package and local export state.
- Learner feedback was submitted in the isolated QA database and reached the recorded state.
- All inspected pages returned meaningful content; browser console error logs were empty.
- The checked-in stylesheet loaded from the local static route with DEBUG disabled.
- Product verification passed all 91 tests, system checks, migrations check, formatting, lint, and
  static collection.

## Closed iteration findings

1. **P1 — missing visual styling in the documented local run command.** The stylesheet previously
   returned 404 because DEBUG was disabled. Fixed with an explicit, loopback-product local static
   route plus an automated configuration test.
2. **P2 — decision actions did not match the target's compact action row.** Replaced radio controls
   plus a second submit button with direct Reject, Amend, and Approve submit actions that still
   lead to the existing confirmation gate.
3. **P2 — capacity summary lacked the target's semantic grouping.** Added a restrained
   emerald-tinted capacity surface while retaining accessible text labels.
4. **P2 — mobile action targets were 42 px high.** Increased buttons, inputs, and mobile navigation
   targets to at least 44 px; remeasurement confirmed 313 × 44 px decision actions.

No P0, P1, or P2 findings remain open.
