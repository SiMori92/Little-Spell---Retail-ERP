# Benchmark UI Design and Implementation Handbook

Version 1.0 · 22 November 2026 · Implementation baseline `2b934db`

Use this handbook to build related SetSail web apps with the visual identity established by Doc Search Benchmark: warm ivory workspaces, dark blue controls, restrained serif headings, and Impressionist artwork around precise analytical interfaces. Product names, navigation, and workflows can change; these visual and interaction principles should remain recognisable.

The **Brand standard** sections define what related apps should preserve. **Current implementation** sections record the working benchmark app. **Adoption guidance** describes how to reuse or improve it. This is a repository design reference, not an installed component package.

## Contents

1. [Brand standard](#brand-standard)
2. [Colour system](#colour-system)
3. [Typography and icons](#typography-and-icons)
4. [Layout and responsive behaviour](#layout-and-responsive-behaviour)
5. [Component specifications](#component-specifications)
6. [Artwork system](#artwork-system)
7. [Interaction and content rules](#interaction-and-content-rules)
8. [Current implementation map](#current-implementation-map)
9. [Adopting the brand in another app](#adopting-the-brand-in-another-app)
10. [Acceptance checklist](#acceptance-checklist)
11. [Maintenance and known gaps](#maintenance-and-known-gaps)

## Brand standard

The interface should feel calm, capable, and human. Artwork provides atmosphere; controls and data provide clarity. Use a familiar SaaS layout with a persistent navigation area, clear page identity, one prominent action per task area, and readable surfaces for work.

Preserve these rules across products:

- Use warm ivory for the workspace and near-white for content panels.
- Use dark water blue for primary actions, selection, and meaningful links.
- Pair restrained serif page titles with sans-serif controls and body text.
- Place Impressionist artwork in an isolated page-header region. Keep text beside it, on an opaque surface.
- Keep tables, forms, scores, and evidence panels free of paintings and textures.
- Use muted sage, lilac, and peach accents sparingly. These decorative accents carry no success or failure meaning.
- Reserve red, green, and amber for clearly labelled states.
- Show limitations and failures beside the figures they qualify.

For example, a related customer-support analytics app can use the same ivory shell, blue “Create report” action, serif page title, and painted header. Its ticket table should remain flat and legible, with explicit “Overdue” labels rather than decorative colours suggesting urgency.

Avoid full-screen paintings behind dashboards, pastel body text, distressed fonts, hand-drawn controls, animated brushstrokes, glass effects over evidence, and large promotional banners above routine work. The brand comes from a few consistent decisions, not decoration on every component.

## Colour system

### Current implementation

These variables are defined in [app/globals.css](app/globals.css). Copy the values exactly when establishing a related app.

| CSS variable    | Value                  | Role                                         |
| --------------- | ---------------------- | -------------------------------------------- |
| `--blue`        | `#355f87`              | Primary controls, selected navigation, links |
| `--blue-dark`   | `#284a6b`              | Primary button hover                         |
| `--text`        | `#263449`              | Main text and metric values                  |
| `--muted`       | `#626e79`              | Supporting copy and table text               |
| `--line`        | `#dedfd9`              | Borders and separators                       |
| `--bg`          | `#f7f5ef`              | Workspace canvas                             |
| `--surface`     | `#fffefa`              | Cards, navigation, page headers              |
| `--accent-soft` | `#eaf0ef`              | Selected and active surfaces                 |
| `--green`       | `#226850`              | Success text                                 |
| `--red`         | `#a43939`              | Failure text                                 |
| `--shadow`      | `0 4px 20px #26344905` | Very subtle card elevation                   |

Additional values currently live in component rules rather than root variables:

| Usage                                | Foreground or accent                       | Background                  |
| ------------------------------------ | ------------------------------------------ | --------------------------- |
| Success badge                        | `#226850`                                  | `#eaf7f2`                   |
| Failure badge                        | `#a43939`                                  | `#fff0ee`                   |
| Pending badge and evaluation caution | `#84621e`                                  | `#fbf5e8` for badges        |
| Active badge                         | `#355f87`                                  | `#eaf0ef`                   |
| Neutral badge                        | `#626e79`                                  | `#f0f3f7`                   |
| Secondary button                     | `#40536a`                                  | `#ffffff`; border `#cbd1cd` |
| Keyboard focus                       | `#5c7e98`                                  | 3px outline with 3px offset |
| Decorative metric accents            | `#9aafbd`, `#9caa90`, `#aaa0b9`, `#c3a58f` | Near-white card             |

The metric accents are assigned by card position using `:nth-child`. A sage accent on the second card does not mean that metric is successful.

### Brand standard

Keep the primary action and text colours stable while individual paintings change. Do not derive live chart series, status colours, or button colours from the current painting. Charts need stable, distinguishable series colours and labels across visits.

Calculated contrast for representative pairs is approximately 12.46:1 for main text on the panel surface, 4.78:1 for muted text on ivory, and 6.69:1 for white on primary blue. Those pairs meet the WCAG AA normal-text threshold of 4.5:1. Recheck new combinations, opacity, and text over images; these figures do not certify the entire app.

## Typography and icons

### Current implementation

No remote fonts are loaded. The app uses the operating system sans-serif stack and a local serif stack.

```css
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
h1 {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 38px;
  font-weight: 400;
  letter-spacing: -1px;
  line-height: 1.25;
}
code,
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
```

| Element                              | Effective size and treatment                                                         |
| ------------------------------------ | ------------------------------------------------------------------------------------ |
| Shared page title                    | 38px desktop; 34px at widths up to 1150px; 30px within the shared header up to 650px |
| Header description                   | 14px; 13px up to 650px; line height 1.6                                              |
| Header eyebrow                       | 10px, weight 700, uppercase; letter spacing 1.8px desktop and 1.2px mobile           |
| Section titles in panels             | 16px, sans-serif                                                                     |
| General H2 and H3                    | 17px and 15px respectively; component rules can override                             |
| Format help panel title              | 24px, Georgia, weight 400                                                            |
| Body                                 | 14px                                                                                 |
| Buttons and table body               | 13px; compact buttons 12px                                                           |
| Supporting labels and table headings | Generally 12px                                                                       |
| Metric values                        | 32px; 28px up to 650px; tabular numerals                                             |
| Pass rate and coverage values        | 18px; tabular numerals                                                               |
| Artwork caption                      | 12px; 11px up to 900px                                                               |

Icons come from `lucide-react`. Navigation icons are 18px; action icons commonly use 15–17px. Keep stroke icons visually consistent. An icon supporting a text label should not replace that label except in compact navigation or a clearly named icon control.

### Brand standard

Use serif typography for page identity and occasional editorial help headings. Use sans-serif for task instructions, controls, tables, and long explanations. Keep essential supporting copy at least 12px. Eyebrows may be smaller because they supplement a full title; never place essential instructions only in an eyebrow.

## Layout and responsive behaviour

### Current implementation

The workspace combines `Shell`, `PageHeading`, and page-specific content. `Shell` is mounted once by the root layout; pages supply their content inside its `main` landmark.

| Viewport         | Effective layout                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Above 1150px     | Fixed 222px sidebar; content starts at the same offset; topbar 65px high; main padding 43px 40px 36px                     |
| 1150px and below | Sidebar and content offset 206px; main padding 32px 25px; shared title 34px                                               |
| 900px and below  | Header artwork stacks below text; upload panels stack; metric grid becomes two columns                                    |
| 650px and below  | Sidebar becomes a 60px icon rail; content offset 60px; topbar 57px high; main padding 30px 16px; shared header title 30px |
| 1500px and above | Main top padding becomes 50px; upload dropzone minimum height becomes 300px                                               |

The main container has a maximum width of 1540px. The mobile navigation is an icon rail, not a drawer. Link `aria-label` values preserve navigation names when visible text is hidden.

The shared header has a 216px minimum height, a 16px radius, a 1px border, and a 30px bottom margin, reduced to 23px on mobile. Its desktop column definition is `minmax(0, 1.5fr) minmax(220px, 1fr)`. Up to 1150px it becomes `minmax(0, 1.6fr) minmax(180px, 1fr)`. Up to 900px it becomes one column. Header content padding is 30px 32px, then 26px, then 23px 20px on mobile.

Artwork uses a cover crop at `center 55%`. The stacked version uses `center 60%` with a minimum height of 100px, reduced to 82px on mobile. Review crops whenever adding a painting: the header is a decorative crop, not a reproduction of the complete composition.

### Adoption guidance

Use an approximately 4px spacing rhythm for new components: 4, 8, 12, 16, 20, 24, 32, and 40px. This is guidance for new work, not an existing spacing-token API; the current CSS also uses values such as 18, 21, and 23px.

Keep horizontal scrolling inside wide tables. The Runs table has a minimum width of 1020px and the Records table 1050px. Preserve usable type rather than shrinking whole tables to fit a phone. Check the page itself for overflow at 375px and 390px widths. The current metric grid stays at two columns on mobile; a new app may use one column if labels require more room.

## Component specifications

### Page identity

Reuse [PageHeading](components/page-heading.tsx) rather than duplicating its structure.

| Prop          | Type        | Required | Purpose                           |
| ------------- | ----------- | -------- | --------------------------------- |
| `eyebrow`     | `string`    | Yes      | Short context above the title     |
| `title`       | `string`    | Yes      | The page H1                       |
| `description` | `string`    | Yes      | One clear statement of the task   |
| `action`      | `ReactNode` | No       | Primary or supporting page action |

This example uses the current API after the shared components and stylesheet have been copied or made available:

```tsx
import Link from "next/link";
import { Plus } from "lucide-react";
import { PageHeading } from "@/components/page-heading";

export function ReportsHeading() {
  return (
    <PageHeading
      eyebrow="YOUR REPORTING WORKSPACE"
      title="Customer reports"
      description="Review service performance and identify cases that need attention."
      action={
        <Link className="button primary" href="/reports/new">
          <Plus size={17} /> Create report
        </Link>
      }
    />
  );
}
```

A page using this component should not add a second H1. The artwork is handled by its child `ArtworkHeader`.

### Panels and metrics

`.panel` provides the near-white background, 1px border, 14px radius, and subtle shadow. It does not provide universal internal padding. `.upload-panel`, `.format-panel`, `.metric`, and `.panel-title` supply their own spacing.

`.metric-grid` uses four columns and an 18px desktop gap, becoming two columns up to 900px. Metric cards pair a concise label and icon with one prominent tabular value. Use the decorative top rules sparingly and retain explicit status labels where needed.

### Buttons and controls

| Class               | Current specification                                   | Appropriate use            |
| ------------------- | ------------------------------------------------------- | -------------------------- |
| `.button.primary`   | Blue fill, white text, no shadow                        | Main action in a task area |
| `.button.secondary` | White fill, subtle border, dark text                    | Supporting action          |
| `.button.small`     | 12px text, minimum height 31px, padding 6px 10px        | Compact contextual action  |
| `.icon-button`      | Minimum 32px square, transparent background, hover tint | Named icon control         |

The base button is 13px, weight 600, radius 8px, minimum height 42px, and padding 10px 15px. Use links for navigation and buttons for actions. Set `type="button"` for non-submit buttons inside forms.

Disabled buttons use 0.5 opacity and a not-allowed cursor. In-progress actions use explicit text such as “Starting…” or “Queuing…” and disable duplicate submissions. There is no shared loading-button component.

Native selects have a 35px minimum height; the Records toolbar raises this to 40px. Search text is 13px. Keep labels explicit, even when the label is visually hidden.

### Status and feedback

`Badge` from [components/common.tsx](components/common.tsx) takes a `value: string` and formats its visible name. Styled variants include `succeeded`, `completed`, `active`, `running`, `failed`, `interrupted`, `queued`, and `pending`. Dimension results have additional `.dim-*` styles. Unknown values receive neutral styling; explicitly design any new status rather than assuming it has a semantic colour.

`ErrorBox` takes `message: string`, renders nothing for an empty message, and otherwise renders an inline error with `role="alert"`. `.alert.warning` and `.alert.info` are CSS patterns used separately; they are not exported React components. Error-alert colours differ slightly from failure-badge colours in the current CSS.

Loading, empty, failed, unavailable, and zero are distinct states. For example, “No runs yet” should offer the next action; an API failure should provide an error and a useful recovery path. Do not turn a failed request into a reassuring empty state.

### Tables and disclosure

Use a panel around a `.table-wrap`, semantic table markup, and column headings. The Runs wrapper is a focusable labelled region so keyboard users can reach the scrolling area. New wide tables should follow that pattern.

The Runs table prioritises run identity, status, progress, pass rate, requirement coverage, latency, and evaluation details. Search failures, interrupted requests, critical failures, and evaluation failures stay visible. Native `details` and `summary` disclose secondary metrics and regrading actions without making the whole row a click target.

Keep the same principle in related apps: expose the information needed to decide; disclose supporting diagnostics. An overdue ticket count belongs in the summary, while request headers belong in the detail view.

### Dialogs

`Modal` from [components/common.tsx](components/common.tsx) accepts `title`, optional `subtitle`, `children`, and `onClose`. It uses a native `dialog`, calls `showModal()`, associates its title and description, focuses the close button, and restores previous focus on cleanup. Escape and clicks targeting the dialog backdrop request closure through `onClose`.

Desktop width is `min(1100px, 94vw)` and maximum height is 92vh. Mobile width is 97vw and maximum height 96vh. Structure content using `.modal-body` and `.modal-footer`; the body scrolls while the outer dialog remains contained. Busy-state closure policy belongs to the caller.

The benchmark setup currently uses a substantial review dialog. A dedicated multi-step setup page was discussed but has not been implemented.

## Artwork system

### Collection and attribution

The collection is a URL catalogue of 131 public-domain Impressionist and Post-Impressionist works (`lib/artwork-catalog.json`, W-79), built from the Google Art Project scans on Wikimedia Commons by `scripts/build-art-catalog.mjs`. Only one image is stored locally, as the offline fallback.

[public/art/README.md](public/art/README.md) records the image sources, rights, and Google Arts & Culture references. Images are local JPEGs with a maximum edge of 1200px. Google Arts & Culture is a discovery and reference destination, not a live image feed. A new work needs its own verified reuse rights; its appearance on Google does not establish permission to copy it.

The caption displays artist, title, and year and opens the matching Google Arts & Culture reference in a new tab using `noopener noreferrer`. Its accessible name also announces the new tab. The painted region is a decorative CSS background rather than a content image with alt text. If a future app asks people to study the painting itself, use a proper image with meaningful alt text and access to the uncropped work.

### Selection lifecycle

[lib/artwork.ts](lib/artwork.ts) owns the catalog and Fisher–Yates shuffle. [ArtworkHeader](components/artwork-header.tsx) owns browser lifecycle and image loading.

1. The initial server and client render show a neutral art area, without a random server-selected painting.
2. After mounting, a deferred effect selects the next work and preloads it with `Image`.
3. After a successful load, the image and matching caption appear together.
4. Each bag contains every catalogued work once. The next bag cannot start with the last work of the previous bag.
5. The remaining bag and last selection persist under `benchmark-artwork-shuffle-v1` in `sessionStorage`.
6. Mounting or a pathname change selects another work. A persisted `pageshow` event also selects another work after a back/forward cache return.
7. Polling re-renders and query-string filter changes do not themselves trigger selection. There is no timed rotation.
8. Cleanup removes listeners and pending image callbacks. Deferring selection avoids consuming an extra work during React Strict Mode's discarded initial effect.

With storage blocked, an in-memory bag still supports navigation, but no-repeat history cannot survive a full reload. New independent sessions have independent orders and can coincidentally start with the same work. Failed image loading falls back to the first catalog work, so error fallback can repeat a painting.

### Adding another painting

Add a rights-checked, sensibly compressed local image under `public/art/`. Add its stable ID, artist, title, year, local image path, and verified source link to `artworks`. Update the attribution README and bump the storage key so existing sessions start a fresh bag. Inspect the desktop and shallow mobile crops and run the artwork tests. Do not put a remote image URL into the catalog's local-image field.

## Interaction and content rules

### Brand standard

Use task-oriented labels such as “New benchmark”, “Choose CSV file”, and “Regrade saved answers”. State what will happen, distinguish a retry from a new operation, and describe errors in language that helps the person recover. Keep credentials, tokens, and backend details out of routine task instructions unless they are needed to configure the task.

Keep decoration stable while a person works. Loading benchmark data must not reshuffle artwork or move the main action. Avoid optimistic success messages before the action has completed.

### Metric integrity in the current app

The implementation in [lib/schema.ts](lib/schema.ts) controls these definitions:

- Progress counts terminal search records, including failed and interrupted searches.
- Pass rate is passed divided by passed plus failed requirement decisions. Review and unassessable cases do not contribute to its denominator.
- Requirement coverage is successful requirement-evaluation records divided by all records. It is not interchangeable with the total number of graded answers.
- Average latency uses successful search requests, not queue wait or grading time.
- Incompatible evaluator policies suppress combined mean scores and pass rates.
- Null or unavailable values display an em dash. Zero remains zero.

Reuse the honesty of these patterns in another product, but define that product's metrics separately. For example, a “95% resolution rate” should have its eligible-case count or coverage alongside it, so excluded cases cannot disappear behind an impressive percentage.

`percent()` expects values already expressed on a 0–100 scale; it does not multiply a 0–1 fraction by 100. `latency()` expects milliseconds and formats seconds. `date()` uses the browser's locale through `toLocaleString()`.

## Current implementation map

| Source                                                         | Responsibility                                                                 | Porting note                                                                                     |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| [app/layout.tsx](app/layout.tsx)                               | Metadata, global stylesheet, shared shell                                      | Set the new product's metadata and mount the shell once                                          |
| [app/globals.css](app/globals.css)                             | Tokens, global rules, components, responsive overrides                         | Read the full cascade; later polish rules override earlier declarations                          |
| [components/shell.tsx](components/shell.tsx)                   | Brand area, sidebar, topbar, footer, main landmark                             | Replace product-specific routes and labels; exact path matching currently sets active navigation |
| [components/page-heading.tsx](components/page-heading.tsx)     | Shared heading API and painted header composition                              | Reuse the prop contract                                                                          |
| [components/artwork-header.tsx](components/artwork-header.tsx) | Client selection lifecycle, preload, caption                                   | Depends on React and Next.js `usePathname`                                                       |
| [lib/artwork.ts](lib/artwork.ts)                               | Catalog, shuffle, storage validation and fallback                              | Scope the storage key to the new app                                                             |
| [public/art](public/art)                                       | Local images and attribution                                                   | Copy source documentation with the assets                                                        |
| [components/common.tsx](components/common.tsx)                 | Badge, Modal, ErrorBox, CopyButton, display helpers                            | Also re-exports a benchmark API client; review before copying wholesale                          |
| [components/upload.tsx](components/upload.tsx)                 | Upload, review, setup and recent runs                                          | Product workflow, not a generic brand component                                                  |
| [components/runs.tsx](components/runs.tsx)                     | Metrics, run summaries and disclosures                                         | Reference for analytical hierarchy                                                               |
| [components/records.tsx](components/records.tsx)               | Filters, response table and evidence details                                   | Reference for investigation workflows                                                            |
| [components/cms-access.tsx](components/cms-access.tsx)         | CMS connection and approval-request UI                                         | Product-specific access flow                                                                     |
| [app/cms/approve/page.tsx](app/cms/approve/page.tsx)           | Standalone supervisor approval route                                           | Shell intentionally omits workspace navigation on this route                                     |
| [tests/artwork.test.ts](tests/artwork.test.ts)                 | Shuffle cycles, persistence, corrupt storage, blocked storage and local assets | Preserve tests when reusing the artwork system                                                   |

The current stack is Next.js 16.4.5 App Router, React 19.3.1, TypeScript, plain global CSS, and Lucide icons. The project uses pnpm and declares Node 24.x. There is no Tailwind or shared UI-framework dependency. Follow the installed Next.js documentation and project instructions when modifying framework behaviour.

## Adopting the brand in another app

1. Define the new app's primary task, navigation, and key decision metrics. Keep the brand, but write product-specific labels and explanations.
2. Establish the colour variables and typography above. Retain system fonts unless a shared brand decision changes them.
3. Extract the shell, header, panels, controls, status badges, dialog and table patterns. Preserve responsive and accessibility rules with each pattern.
4. Copy the artwork controller, catalog, images and attribution together. Use an app-specific storage key; replace `usePathname` with that framework's route lifecycle if needed.
5. Replace the current shell's route map, path labels, workspace copy, metadata, and approval-route exception. Do not carry an unrelated CMS bypass into a different app.
6. Keep application APIs and scoring logic separate from reusable presentation components. Configure `@/` imports or replace them with the new app's paths.
7. Use semantic names such as `--color-action` in a future shared token package if useful, mapped to the exact values here. These names are proposed aliases, not variables already available in this app.
8. Validate real task flows, keyboard operation, mobile layouts, caption crops and metric definitions before release.

For a Next.js port, remember that `PageHeading` imports `ArtworkHeader`, which imports `lib/artwork.ts`. Copying only the visible header JSX will omit shuffling and attribution. Copying only the root colour variables will omit typography, layout and responsive behaviour.

### Reusable implementation brief

> Build this app using the branding in the Benchmark UI Design and Implementation Handbook. Use ivory `#f7f5ef`, near-white panels `#fffefa`, ink `#263449`, supporting text `#626e79`, and primary blue `#355f87`. Pair Georgia page titles with system sans-serif controls. Use the shared sidebar and topbar structure, 14px panels, 16px painted page headers, restrained borders, and Lucide stroke icons. Keep data and forms on opaque surfaces. Curate locally stored Impressionist artwork with source attribution, shuffling per visit rather than on a timer. Preserve labelled statuses, keyboard access, mobile layouts, and visible failure information. Adapt routes, labels and metrics to the new product. Use the handbook's acceptance checklist and document any deliberate departures.

## Acceptance checklist

### Visual identity

- [ ] Core colour values match; decorative accents do not encode status.
- [ ] Page titles use the serif stack; controls and data use sans-serif.
- [ ] Each normal workspace page has one H1 and a clear task description.
- [ ] Art stays inside the header; tables and inputs remain readable and opaque.
- [ ] Every painting has a correct artist, title, year, source link and rights record.

### Responsive behaviour

- [ ] Check 1440px, 1150px, 900px, 650px, 390px and 375px viewport widths, including just above and below the breakpoints.
- [ ] Sidebar widths and main offsets agree; icons retain accessible names on mobile.
- [ ] Page content has no unintended horizontal overflow; wide tables scroll internally.
- [ ] Long titles, action labels and captions wrap without covering controls.
- [ ] At 200% zoom, content remains operable and dialogs retain reachable actions.

### Interaction and accessibility

- [ ] Keyboard users can reach navigation, actions, filters and table disclosures.
- [ ] The skip link targets the main landmark; focus indicators remain visible.
- [ ] Dialog title, focus placement, Escape behaviour and focus restoration work.
- [ ] Statuses and errors use text as well as colour; form fields have programmatic labels.
- [ ] Essential text meets contrast requirements, including new state combinations.
- [ ] Reduced-motion preferences are respected. Enlarge compact controls for touch-heavy use; current 31–32px controls are not a universal 44px target standard.
- [ ] Loading, empty, error, zero and unavailable states are tested separately.

### Artwork and data behaviour

- [ ] Visits and refreshes advance the artwork; ordinary polling does not.
- [ ] Every painting appears once per bag, including after reloads; cycle boundaries do not immediately repeat under normal storage and successful loading.
- [ ] Back/forward navigation, storage denial, damaged stored state and image failure have sensible behaviour.
- [ ] A caption always matches the displayed image.
- [ ] Failures and incomplete coverage remain visible beside headline metrics.

For implementation changes in this repository, run `pnpm typecheck`, `pnpm lint`, `pnpm exec vitest run tests/artwork.test.ts`, and `pnpm build`, plus tests relevant to any changed behaviour. These commands do not replace browser review or a full accessibility audit. Documentation-only changes need source and link checks rather than a rebuild.

## Maintenance and known gaps

The current design is a working app style, not a fully extracted design system. Colours, spacing, radii and some control states remain hardcoded. Global selectors such as `main`, `h1`, `table` and `summary` can affect unrelated screens. Later polish rules and media queries override older definitions, so the first declaration of a class may not describe its final appearance.

Primary hover styling currently uses `:hover:enabled`, which applies to enabled buttons but does not provide the same hover rule for navigation links styled as buttons. New shared controls should cover both element types. Compact controls and small artwork or eyebrow labels need contextual review rather than automatic reuse for every audience.

The implemented scheme is light-only. There is no exported token package, Storybook catalog, theme switcher, timed gallery, live Google gallery API integration, or implemented multi-step benchmark wizard. Full browser visual regression coverage and a full accessibility audit are not established by the current build and unit checks.

When the brand evolves, update this handbook with the corresponding token, component, asset and test changes in the same revision. Prefer consolidating existing overrides over adding another layer. Record intentional departures in each related app so a local exception does not silently become a new family-wide convention.

## Little Spell ERP adoption — 22 November 2026

The active implementation is the Next.js ERP. The archived Django application is
not its deployment source. The ERP retains its installed Node 22, Next.js, React,
Tailwind/global CSS, Radix dialogs, TanStack Table and Recharts stack.

### Implemented patterns

- `src/app/globals.css` maps the handbook colours to existing ERP variables.
  `--primary` is an action colour; `--success` is a separate semantic colour.
- `src/components/page-heading.tsx` provides one page title, description and action
  area across Today, Sell, Buy, Stock, Money, Close, Reports and Setup. Dataset
  transition and transaction flows use compact headers without mounting artwork.
- `src/components/ui/workspace.tsx` provides shared status badges, metric cards,
  flow progress and inline feedback. The four-step review sequence and all
  server-side accounting checks remain in place.
- `src/components/report-library.tsx` groups and searches all 18 report views.
  Report links preserve the selected reporting month. Missing evidence and the
  MODELLED/ACTUAL qualifications remain visible beside figures.
- `src/components/close-checklist.tsx` displays each computed gate, its source
  reason, evidence disclosure and the first unresolved check. It never replaces
  a domain-computed result with a presentation-derived result.
- Money exposes one primary expense action and groups supporting actions by task.
  Stock distinguishes unavailable opening value from zero. Setup displays recorded
  progress instead of milestone identifiers. Guides use native disclosures.
- Shared tables retain internal scrolling and an explicit keyboard record action.
  Purchasing drawers retain focus management, Escape closure and reachable actions.

### Deliberate adaptations and review follow-up

Working headers omit artwork entirely; entering a form does not download a hidden
painting or consume a shuffle entry. Landing pages rotate a URL catalogue of 111
public-domain Google Art Project scans hosted on Wikimedia Commons
(`src/lib/artwork-catalog.json`, built by `scripts/build-art-catalog.mjs`) plus one
local offline fallback, Monet's _Water Lilies_ — 112 works per bag under
`little-spell-artwork-shuffle-v2`. A failed remote load falls back to the local
image; if that also fails, the header stays neutral and unattributed. Per-work
sources, rights and Google Arts & Culture references are recorded in the catalogue
and `public/art/README.md`. Decorative accents never imply a result.
Essential supporting text and financial previews use at least 12px text.

**Finance wording review remains outstanding:** review the plain-English G-1…G-5
headings and recovery suggestions in `close-checklist.tsx`. These are explanatory
copy, not new accounting policy. G-5 explicitly directs corrections through a new
reviewed entry, preserving immutable history. The financial parity limitations in
`PARITY_TIEOUT.md` remain separate from UI acceptance.

Recharts' inner wrapper must not receive `max-width: 100%`: its parent measurement
shim has zero width, so that rule collapses otherwise measured plots. Let
`ResponsiveContainer` size the plots; keep their surrounding cards shrinkable.
The rollout browser test checks real plot dimensions on desktop and mobile.

### Verification and deployment boundary

Use `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build`, `pnpm smoke` and
`pnpm e2e`. Browser tests use isolated synthetic workspaces. Review all workspace
routes at 1440, 1150, 900, 650, 390 and 375px; the pilot tests additionally exercise
breakpoint boundaries, artwork failures, blocked storage and keyboard navigation.

Railway's existing GitHub integration deploys `main` automatically. This UI change
has no modifications to domain logic, API handlers, storage code, `Dockerfile`,
`railway.json` or CI configuration. Merging deploys the new interface against the
existing mounted store; UI acceptance does not establish financial release readiness.

Final local verification: typecheck, lint, 134 unit/API/store tests, production
build, isolated production smoke, 39 Chromium end-to-end tests, and tracked/staged
repository guards passed. The artwork tests cover the 112-work bag, the local
offline fallback, remote-failure fallback, blocked storage and bag advancement.
Lint retains three existing warnings; the build retains four existing
filesystem-tracing warnings. Desktop/mobile screenshot review of Close, Money,
Reports, Sell and Stock produced no browser console errors. These checks do not
constitute a full accessibility audit or financial-parity sign-off.
