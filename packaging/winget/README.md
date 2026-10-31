# winget manifests (prepared, not submitted)

`manifests/y/ymmiah/AutoMotoAI/<version>/` follows the layout of
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs). The installer is the per-user NSIS `.exe`
from the GitHub Release; `InstallerSha256` is its SHA-256 from the release's `SHA256SUMS.txt`.

**Licence:** the manifests for 5.6.0-beta.1 to beta.3 say `License: MIT` and link to the LICENSE at their own tag,
because those versions were MIT. From the next version on, use:

```yaml
License: AGPL-3.0-only
LicenseUrl: https://github.com/ymmiah/AutoMotoAI/blob/v<version>/LICENSE
Copyright: Copyright (C) 2025-2026 Yasin Mohammed Miah
CopyrightUrl: https://github.com/ymmiah/AutoMotoAI/blob/v<version>/NOTICE
```

How to validate, test and submit: [docs/WINDOWS-DISTRIBUTION.md](../../docs/WINDOWS-DISTRIBUTION.md#winget-windows-package-manager).
