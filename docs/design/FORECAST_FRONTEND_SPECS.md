# Forecast twin: the two remaining frontend delegation specs

Written 2026-11-17 for `docs/design/FORECAST_TWIN_PLAN.md` section 7.2. Each block is a
self-contained prompt for one delegated coding run; run them in order and gate each one
(lint, build, the check scripts, then the real page in a browser).

## F2a: the three presentational components

```text
Stack: React 19, TypeScript 5.9 (strict), Vite, Tailwind 3. Repo: cardio-twin. Work ONLY in frontend/. Do not commit. Do not touch backend/.
Read first:
 - tools/mockups/forecast_template.html : the APPROVED mockup. Its HTML/CSS and its render() script are the visual and behavioural reference for this task: layout, wording, order, the three source labels, the status badges, every state. Copy the wording exactly.
 - frontend/src/twin/assessment.ts : types and pure helpers already written (AssessmentOptions, AssessmentAnswer, Entries, setEntry, entryText, groupProgress, totalProgress, statusText, changeText, scaleTop, displayUnit ...). Use them; put NO parsing or arithmetic in a component.
 - frontend/src/components/plan/PlanEditor.tsx and PlanResult.tsx : the house style to copy exactly - Tailwind class vocabulary (rounded-card, rounded-el, bg-surface-low, text-ink/70, border-white/10, bg-oxy-container, text-warn, border-warn-strong, font-mono readout ...), FOCUS_CLASS, 44px controls, how a column and a section card are built. Use ONLY tokens that exist in frontend/tailwind.config.js; if the mockup needs a colour that has no token, use the nearest existing token rather than a raw hex.

TASK: three presentational components in frontend/src/components/plan/. They take props and call callbacks; they fetch nothing and hold no server state. Do NOT wire them into PlanPage, PlanEditor or PlanResult in this task.

1. HealthColumn.tsx
   props: { options: AssessmentOptions; entries: Entries; onEdit: () => void; onFillExample: () => void; onClear: () => void }
   A column the same size and style as the Day column of PlanEditor: heading "Your health", "<given> of <of> entered" (marked done by text and a tick, not colour alone), one row per group with its "given / of", the buttons "Enter or edit" (primary), "Fill with invented example" (only when options.example exists; its accessible description is options.example.label) and "Clear" (only when something is entered), and the note "Held on this device only. Not saved on the server and not part of the link."

2. HealthDrawer.tsx
   props: { open: boolean; options: AssessmentOptions; entries: Entries; onChange: (entries: Entries) => void; onClose: () => void; refused: { attribute: string | null; message: string } | null; focusAttribute: string | null }
   A right-hand panel (role="dialog", aria-modal="true", aria-labelledby its heading; full width under 640px, 560px otherwise), as in the mockup. Heading "Your health", button "Done". Intro: "Enter what you know. Anything left empty is asked for by the result that needs it; nothing is assumed."
   Per group a heading, per entry a row: a <label> bound to its control; kind number -> a text input with inputMode="decimal", the unit beside it, placeholder "<min> – <max>", dashed border while empty; kind yesno -> two buttons Yes / No with aria-pressed (pressing the pressed one again clears the answer); kind choice -> one button per option, same rule. Under each: the entry's why text, plus " · not entered" when empty.
   Typing calls setEntry; when setEntry returns a message, show it under that field (role="alert", text-warn) and keep what the person typed in the box (local draft state) so they can correct it; a valid value clears the message. A server refusal (props.refused) shows under its field the same way, or at the top of the panel when attribute is null.
   Behaviour: when it opens, focus moves to the field named by focusAttribute, else the first control; Escape and "Done" call onClose; Tab stays inside the panel while open; when closed it renders nothing interactive (not just hidden off-screen for keyboard users). A dimmed backdrop behind it closes it on click. No animation is required; if you add one, respect prefers-reduced-motion.

3. WeekRisk.tsx
   props: { answer: AssessmentAnswer; onEnter: (attribute: string | null) => void }
   The three panels of the mockup in a grid (one column under 1100px): "Weekly activity", "Risk of disease", "Flags", and the legend of the three source labels ("Measured from recordings", "Projected by this person's model", "Population model applied to you"), each label carrying its own glyph so colour is not the only signal.
   - Weekly activity: an axis from 0 to scaleTop(...), ticks every 5, the range band, a whisker from current.p10 to current.p90, a "Now" marker at current.p50 above the axis, a "With this plan" marker at planned.value below it. Build it with positioned divs or one inline SVG; it must have a text alternative (role="img" with an aria-label that states the three numbers). Under it the rows exactly as in the mockup (Measured: now, median of N weeks; Projected: sessions, N × per-day; Measured: everyday movement; With this plan; the range row with a "Placeholder value" badge), then the habit rule sentence. When planned is null show dose.reason (or "Press Run to project the week.") in the dashed box. When current is null say "No full week in the recordings yet." and draw no marker for it.
   - Risk of disease: per result: label, period, the status badge from statusText, then one of: not_applicable text; "Needs: <labels>" with a button "Enter" that calls onEnter(first missing attribute); the figures Now / With this plan and the change chip from changeText (down, up or same marked by a glyph as well as colour); "With a plan: press Run" when planned is null but now exists and nothing is missing; the reason sentence when present. A <details> "What stands behind it (N steps)" lists each model: name, source, status.
   - Flags: raised -> label, text and the status badge; clear -> topic and "No flag from what you entered."; not_answered -> topic, "Not answered. Needs: <labels>" and an "Enter" button calling onEnter. Then the sentence "A flag repeats what guidance says for what you entered. No flag is not a statement that exercise is safe."
   Numbers: one decimal for doses and risks, as the mockup. Units through displayUnit.

RULES for all three:
- No attribute id, unit, disease name, model name or threshold may be written in a component: every label comes from props.
- Every interactive control is at least 44px high and has a visible focus style (FOCUS_CLASS); text is at least 13px; contrast at least 4.5:1 with the existing tokens.
- No `any`. No new dependency. No console.log. Nothing entered may be written to the URL, localStorage or the console by these components.

GUARD: a component must not crash on a legitimate empty state (no example, no range, current null, planned null, zero results, zero flags). Handle each explicitly.

REUSE: before writing a helper, grep frontend/src for one that exists (clock, unitText, FOCUS_CLASS, formatting helpers) and import it; export it from its module if it is private.

RUN: from frontend/ run and paste the real output of: npm run lint ; npm run build ; node --experimental-strip-types scripts/assessment-check.ts . A type check alone is not evidence.
VERIFY: grep -n "^export function" frontend/src/components/plan/HealthColumn.tsx frontend/src/components/plan/HealthDrawer.tsx frontend/src/components/plan/WeekRisk.tsx and paste it.
```

## F2b: wiring them into the Plan a day page

```text
Stack: React 19, TypeScript 5.9 (strict), Vite, Tailwind 3. Repo: cardio-twin. Work ONLY in frontend/. Do not commit. Do not touch backend/.
Read first: tools/mockups/forecast_template.html (the APPROVED mockup: where things sit and what they say); frontend/src/components/plan/PlanPage.tsx, PlanEditor.tsx, PlanResult.tsx (the page to extend); frontend/src/components/plan/HealthColumn.tsx, HealthDrawer.tsx, WeekRisk.tsx (already written, props only); frontend/src/twin/assessment.ts and the functions findAssessmentLamina / fetchAssessmentOptions / runAssessment / EntryRefusedError in frontend/src/utils/api.ts; frontend/src/twin/planDay.ts (encodePlan / decodePlan / planBody / parsePlannedDay).

TASK: wire the health section, the week control and the "week and risk" result into the Plan a day page.

1. Boot (PlanPage): after the plan options load, call fetchAssessmentOptions().
   - null (no lamina declares the view): the page behaves EXACTLY as it does today. No health column, no tabs, no banner, Run calls runPlan. This path must stay byte-for-byte the same on screen.
   - it throws: the page still works as today, plus one line above Setup: "The health section could not be loaded." with a Retry button that asks again.
   - options: the rest of this task applies.
2. State (PlanPage): entries (Entries, starts {}), daysPerWeek (starts at the `days` URL parameter when it is an integer 0..7, else 3), the last AssessmentAnswer, the result tab ('day' | 'week', starts 'day'), drawer open / focusAttribute, entry refusal.
   - The entered values live in React state only. They are NEVER written to the URL, to localStorage or sessionStorage, or to the console. The plan link keeps its `plan` parameter and gains `days=<n>`; nothing else.
3. Banner: above Setup, when assessment options exist: "Research demonstration · not medical advice" followed by " · " and options.notice when it is not null. Same warn styling as the existing notice line.
4. PlanEditor: HealthColumn is the FIRST column, before Day. In the action row, after Run: the words "Repeat this day", a stepper (buttons "−" and "+" with aria-labels "One day fewer" / "One day more", at least 44px, disabled at 0 and 7, the number between them in an <output>), then "days a week". Pass what it needs through new optional props so PlanEditor still renders as today when they are absent.
5. Run: when assessment options exist, Run calls runAssessment(lamina, { subject, entries: entriesBody(options, entries), plan: planBody(...), days_per_week: daysPerWeek }), gives the returned `day` to parsePlannedDay exactly as runPlan's answer is treated today, and stores the answer. The chart, play cursor and every existing state keep working as today.
   - EntryRefusedError: phase 'refused'; open the drawer focused on that field (controlForEntryField) with the server's message under it.
   - PlanRefusedError and other failures: as today.
6. Staleness: changing an entry, filling the example, clearing, or changing days a week after a run marks the result "Setup changed" exactly as a slider move does today (same dimming, same "Run again" overlay). It does not rerun by itself.
7. PlanResult: when an assessment answer exists, a tab row sits at the top of the result: "The day" and "The week and risk" (role="tablist" / "tab" / "tabpanel", arrow keys move between tabs, the selected one marked by more than colour, 44px). "The day" shows today's result unchanged. "The week and risk" shows WeekRisk. The dimming and the "Run again" overlay cover whichever tab is shown. WeekRisk's onEnter opens the drawer focused on that attribute.
8. Drawer: render HealthDrawer once at page level. Closing it returns focus to the control that opened it.

CONSTRAINTS:
- Recorded days and the tab row above the views are untouched.
- No attribute id, unit, disease or model name in any component.
- At 1920x1080 with the default plan, Setup, Run and the top of the result must still fit as in the mockup: the health column has the same width as the others and the row still scrolls sideways when columns do not fit.
- No `any`, no new dependency, no console.log.

GUARD: every value that comes from the server or the URL is checked before use (the `days` parameter: integer 0..7 or ignored). A failed or refused run must never leave a stale risk figure on screen looking current: it is dimmed like the chart.

REUSE: grep before writing a helper; import what exists.

TESTS: extend frontend/scripts/assessment-check.ts (or plan-check.ts for the link) with checks for anything pure you add (for example reading `days` from a query string, writing it back). They must pass.

RUN: from frontend/ run and paste the real output of: npm run lint ; npm run build ; node --experimental-strip-types scripts/assessment-check.ts ; node --experimental-strip-types scripts/plan-check.ts ; node --experimental-strip-types scripts/dayview-check.ts . A type check alone is not evidence.
VERIFY: grep -n "runAssessment\|HealthDrawer\|WeekRisk\|HealthColumn" frontend/src/components/plan/PlanPage.tsx frontend/src/components/plan/PlanEditor.tsx frontend/src/components/plan/PlanResult.tsx and paste it.
```
