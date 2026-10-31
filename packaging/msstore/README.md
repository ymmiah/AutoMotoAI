# Microsoft Store kit (AutoMoto AI Beta)

Everything to fill in the Store listing in Partner Center. Copy and paste; edit freely.
Step-by-step instructions are in [docs/WINDOWS-DISTRIBUTION.md](../../docs/WINDOWS-DISTRIBUTION.md#chosen-route-the-microsoft-store-msix).

| File | Use it for |
|---|---|
| [`listing.md`](listing.md) | Store listing: name, descriptions, features, search terms, URLs, licence terms |
| [`age-rating.md`](age-rating.md) | the IARC age-rating questionnaire |
| [`certification-notes.md`](certification-notes.md) | *Submission options → Notes for certification*, and the restricted-capability reason |
| [`screenshots/`](screenshots) | desktop screenshots, 1920x1200 PNG (the Store wants 1366x768 or larger; up to 10) |
| [`images/`](images) | 1:1 app tile icon 300x300 (recommended) and 16:9 hero art 1920x1080 (optional) |
| [`msix.py`](msix.py) | generates the package manifest and maps the version (5.6.0-beta.3 → 5.6.3.0) |

Privacy policy URL: <https://ymmiah.github.io/AutoMotoAI/PRIVACY.html>

The package itself is built by CI: *Actions → Windows app → (latest run) → Artifacts → `automoto-ai-msstore`*,
which contains `AutoMoto-AI-<version>-Windows-x64.msixupload` (upload this) and the `.msix` inside it.
