# UI handbook adoption — Little Spell Ledger (`app/`)

Status: phases 1–5 complete, 2026-11-22. Not yet committed.
Source standard: [`UI_HANDBOOK.md`](../UI_HANDBOOK.md). The handbook asks each related app to record its intentional departures, so that a local exception does not silently become a family-wide convention. This file is that record for the Django ledger. The Next.js console in `erp/` is a separate adoption and is not covered here.

## What the ledger keeps from the handbook

- **Colour values are exact.** Ivory `#f7f5ef`, surface `#fffefa`, ink `#263449`, muted `#626e79`, line `#dedfd9`, blue `#355f87`/`#284a6b`, and the success, warning, danger and neutral badge pairs. Every colour is a variable on `:root` in `static/css/app.css`. The token names differ (`--ink`, `--teal`, `--pale-blue` instead of `--text`, `--green`, `--accent-soft`) but the values are the same.
- **Type:** Georgia titles, system sans-serif controls, 14px body, 13px buttons and tables, tabular numerals on every figure.
- **Layout:** a 222px sidebar, 206px at 1150px and below, and a 60px icon rail at 650px and below; the shared header grid; a 1540px maximum width. The breakpoints are the handbook's.
- **Artwork:** four rights-checked, locally stored paintings with captions linking to Google Arts & Culture, shuffled in a bag per visit (`static/js/workspace.mjs`, attribution in `static/art/README.md`).

## Intentional departures

| # | Departure | Handbook says | Why the ledger differs |
|---|---|---|---|
| 1 | **The SAMPLE banner is a bold red bar above every page, admin included.** | No equivalent; "avoid large promotional banners above routine work." | It is a quarantine control (DATA_REVIEW §A1.3), not decoration, and tests protect it. It uses the handbook red `#a43939` with `#fffefa` text (6.46:1). Never soften it to match the calm palette. |
| 2 | **Report detail pages use a compact header with no artwork.** | Every page uses the painted shared header. | Report pages are working screens, and the figures should start above the fold. Compact headers do not include the artwork panel at all, so viewing a report never loads a painting or advances the shuffle. |
| 3 | **Metric and provenance grids drop to one column at 390px and below.** | Two columns on mobile; "a new app may use one column if labels require more room." | Labels such as "Operational events" and "Overall cost basis" truncate at two columns. This uses the handbook's allowed exception. |
| 4 | **Status tones are conservative, and a file-reported stage is never shown as success.** | Unknown values are neutral; design each status deliberately. | An Instagram "paid" or an Etsy "shipped" comes from a file, not proof, so it stays neutral or blue. Green is only for proven outcomes: CLOSED, PASS, received, dispatched. NOT RUN is grey and is never a pass. Mappings: `core/admin_ui.py`, `templates/includes/status_badge.html`. |
| 5 | **Empty states always say what an empty list does not prove.** | Empty should offer the next action. | In a ledger, "0 rows" is easily misread as "nothing happened". Empty tables, empty admin lists and record-count cards all say a zero is a stored-row count, not a certified empty period. |
| 6 | **The admin is restyled, not rebuilt, and carries no artwork.** | — | Django admin is about 80% of the ops console. It gets the palette, badges and notices through `static/css/admin.css`, but no artwork, because those pages are dense records. |
| 7 | **The admin theme toggle is hidden.** | The scheme is light-only. | `admin.css` forces the light palette, so Django's dark-mode switch would do nothing. |
| 8 | **Header artwork failure leaves a blank pale panel.** | Image failure falls back to the first catalog work. | A blank panel cannot show a caption that does not match the image, and the panel is decorative. |
| 9 | **Icons are inline SVG in a template include, not `lucide-react`.** | Lucide stroke icons. | The ledger is server-rendered Django with no JS build. `templates/includes/icon.html` draws Lucide-style 1.7px strokes at 18px. |
| 10 | **Secondary buttons use `#40536a` on white.** | Same. | Recorded only because the first pass used blue text here and was corrected to the handbook value. |

## Shared components

One implementation each, in `templates/includes/`:

| Include | Purpose |
|---|---|
| `page_heading.html` | Painted shared header; `compact=True` gives the working header without art |
| `artwork.html` | Painting catalogue, read by `workspace.mjs` |
| `notice.html` | `tone` = info, success, warning or danger (danger uses `role="alert"`) |
| `status_badge.html` | Text label always shown; colour reinforces it |
| `section_heading.html` | Eyebrow, H2, description, caption |
| `empty_state.html` | What is missing, and what that does not prove |
| `report_table.html` | Provenance-preserving table; every figure cell keeps `data-dataset-kind`, `data-cost-basis`, `data-source-period`, `data-unit` |
| `error_panel.html` | Error, reason and recovery; used by `error.html`, `400.html` and `404.html` (`500.html` is self-contained because Django renders it without request context) |
| `close_card.html` | Overview close checklist, built from `core/close_summary.py` |

Admin: `core/admin_ui.py` (`BadgeColumnsMixin`), `templates/admin/change_list.html` (empty-list note) and `templates/admin/change_form.html` (read-only note).

## Verification record (2026-11-22)

- **Tests:** the full Django suite passes, 319 tests including 20 in `core/tests/test_handbook_ui.py`, run against a local PostgreSQL 16. The artwork shuffle tests pass with `node --test tests/ui/` (4 tests).
- **Responsive:** 11 pages, including the error and close-card states, at 1440, 1151/1150/1149, 901/900/899, 720, 651/650/649, 640, 390 and 375px: 154 combinations, no page-level horizontal overflow and no console errors. Wide tables scroll inside their panel. A 120-character report title wraps without covering controls. The 720px and 640px runs approximate 200% zoom on 1440px and 1280px screens.
- **Keyboard:** the first Tab reaches a visible skip link, which moves focus to `#main-content`. Navigation, search, period form, report cards, CSV export and the table scroll region are all reachable, each with a 3px `#5c7e98` focus ring.
- **Contrast:** 20 text and background pairings computed, all at least 4.5:1. The closest are muted on the pale-blue notice (4.52), muted on row hover (4.68) and the neutral badge (4.69).
- **States:** loading does not apply (server-rendered); empty, zero, error (400, 404, 500), ABSENT, PROVISIONAL, BLOCKED, NOT RUNNABLE, NOT RUN, CLOSED and REOPENED each have a distinct, labelled presentation and a test.

## Known gaps

- **No full accessibility audit** with a screen reader, and no visual-regression suite. The checks above are scripted spot checks.
- **Close-card wording** (`core/close_summary.py`) was written from the gate code. Finance (Agent 2) should confirm the plain-English gate titles and next steps.
- **Admin record titles** read "Period object (2025-11)" because the models define no `__str__`. Fixing that is a model change, outside this UI work.
