# AutoMoto AI — Invoice & Spreadsheet Intelligence v2

**Second of eight planned milestones. Development only — no store publication.**

## Delivered

The existing private spreadsheet editor now supports an explicitly enabled, offline, bounded formula language, a visible calculated-result panel and a 40-step local Undo/Redo history. The original user-authored cell text and imported spreadsheets are never overwritten automatically.

### Formula language

Allowed in calculation mode:

- Cell references A1:P100 **within the same worksheet**.
- Arithmetic +, -, *, /, ^ (integer powers limited to 12), parentheses and unary signs.
- Numeric/string comparisons =, <>, <, >, <=, >=.
- SUM, AVERAGE, MIN, MAX, COUNT and COUNTA, including bounded cell ranges.
- IF(condition, when_true, when_false) with lazy evaluation of the chosen branch.
- Numeric literals, quoted text strings, TRUE and FALSE.

Examples: =B2*C2; =SUM(D2:D25); =AVERAGE(A1:A10); =IF(A2>50,"High","Low").

The deterministic parser uses an allowlist and **does not call eval, exec, Python's AST evaluator, an AI provider, network services, or arbitrary software tools**. It rejects unrecognised functions, external workbook syntax, scripts, macros and malformed expressions. Cell dependency recursion has cycle detection, caching and execution limits.

### Errors and deterministic limits

User-visible formula errors include #CYCLE!, #REF!, #DIV/0!, #VALUE!, #NAME?, #NUM!, #PARSE! and #LIMIT!. Errors block exports instead of being hidden or replaced by guessed results. Formulas are capped at 300 characters; no more than 500 formulas per workbook, 60 evaluation-depth levels, and 30,000 calculation steps. Workbook dimensions remain limited to five sheets, 100 rows, 16 columns per sheet. These are v2 development limits, not general Excel limits.

### Compatibility and export

**Important backward compatibility:** Existing v1 saved/imported workbooks omit calculation_mode and remain literal. A newly created v2 workbook explicitly opts into formulas; previously imported =-prefixed strings can only become active formulas when the user chooses "Enable safe formulas". This prevents silent re-interpretation of old spreadsheet data.

Saving a workbook preserves the selected mode and original formula text in a new, private, create-only record. When formula mode is enabled:

- XLSX uses *only parser-validated formulas* as genuine spreadsheet formulas. Excel/LibreOffice recalculates on opening; generated XLSX formula-result caches are not promised.
- CSV exports the deterministic calculated values (not the formula strings) and escapes formula-looking text results to protect spreadsheet clients.
- Numeric calculations use Decimal with bounded precision. It is not an accredited accounting/finance engine, and differences from Excel's complete number/date/coercion semantics remain possible.
- Any formula error blocks export; original files and previous saved drafts remain unchanged.

In literal mode, existing v1 XLSX/CSV text and escape protections remain active.

### Editor interaction

- Change cells and select "Recalculate" to inspect updated results and cell dependencies. Recalculation is also triggered after committed cell changes.
- View formula results beside the editable source and in a separate results panel, with error indicators.
- Use Undo/Redo to restore workbook content, names, sheet additions, renamed sheets and calculation mode. Up to 40 immutable snapshots are held **in this session**. This history is not the v7 Document Assistant recovery feature; snapshots are not written to disk automatically.
- Read the explicit status and error messages before exporting.

### Security and acceptance

New authenticated endpoint: POST /api/spreadsheets/calculate (allowed through hosted per-tenant routing). Requests use the existing strict workbook schema; calculation reads no external files and writes no artefacts. The shared app middleware applies rate limiting.

Required regression gates:

- Run python -m pytest -q tests/test_spreadsheet_formulas.py tests/test_spreadsheet_workspace.py.
- Run cd apps/desktop && npm run test:ui.
- Full CI matrix: Python 3.10 and 3.13 on Windows, Linux and macOS, plus Office, hosted security, browser UI, Docker, installers, VS Code and Windows app.
- Manually review formulas, spreadsheet exports, 320px/mobile layout, keyboard workflow and XLSX recalc in installed Excel/LibreOffice. CI does not prove native spreadsheet fidelity or financial/accounting correctness.

### Remaining roadmap

v3 advanced Excel compatibility and editing; v4 branded invoices and quotations with PDF; v5 financial dashboards; v6 optional local AI; v7 integrated business workflows; v8 final production assurance. No Microsoft Store publication is authorised by this milestone.
