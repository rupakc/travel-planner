# Task 8e report: `plan` namespace

Status: DONE.

- Strings: 130 catalogue entries (incl. 9 plural groups) in `frontend/src/i18n/locales/{en,es,de,fr,hi,zh,bn}/plan.json`.
- Files extracted: PlanViewModal, PlanExport, CostBreakdown, BudgetPlanner, BestValuePackage (useTranslation('plan')); utils/planExport.js (.ics) and utils/planPrint.js (print doc) use `i18n.t('plan:...')` at call time, and the print `<html lang>` follows the active language.
- Number formatting moved to `fmtNumber` (USD currency style) in all seven files; no `toLocaleString` / `en-US` left.
- `data-tid` added to every button/link/toggle/input touched (`plan.*`).
- Logic fixes needed for i18n: PlanViewModal status message is now a key (`saved`, `saveFailed`, ...) and error colour is decided by `/Failed$/` instead of `msg.includes('fail')`; PlanExport popup message is a key; BudgetPlanner/BestValuePackage plural helpers replaced by i18next plurals; cost category labels are looked up by key (`cost.cat.*`) with the planHelpers label as default.
- Tests: full vitest suite 83 files / 1161 tests pass unchanged; eslint `--max-warnings 0` clean.

Deliberately left untranslated (not in my files / backend data): `budget.label` ("$X under budget") from planHelpers `getBudgetStatus`; `reason` text and `pkg.budget.label` from bestValuePackage util; SIM coverage rating and tip severity enum values shown raw; activity/hotel names etc.

Concerns: planHelpers/bestValuePackage utilities produce English copy that surfaces in my components (listed above); they belong to another owner. Currency in non-English locales renders as the locale's USD form (e.g. "US$" in zh/es).
