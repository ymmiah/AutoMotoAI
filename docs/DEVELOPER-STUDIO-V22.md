# Developer Studio V22/64 — C# and .NET Engineering

Development-only milestone based on V21 merged into the aggregate development branch. No changes to main, production, user data or the single central AutoMoto Agent.

## Implemented

- Authenticated local-only, **non-executing** inspection of C# project files, .sln/.slnx declarations, global.json, MSBuild properties/targets, NuGet configuration and bounded .cs/.razor/.cshtml files. Input reads use bounded no-follow descriptors and SHA-256 checks.
- defusedxml parsing of MSBuild .csproj manifests rejects malicious XML entities. Reports declared TargetFramework(s), SDK, output type and NuGet packages. Blocks project execution with unreviewed custom SDK, MSBuild Target/Import/UsingTask/Exec/ProjectReference, global targets, custom NuGet config or multi-project solutions.
- Lexical C# namespaces/types, Razor source, heuristic ASP.NET Core, Blazor, xUnit and NUnit recognition. Framework hints are not a substitute for compilation or proof that dependencies are installed.
- SHA-256 discovery of installed dotnet, MSBuild, C# language server and netcoredbg/vsdbg debugger adapter candidates. Inspection never calls the SDK and does not fabricate an installed SDK version. Only separately approved dotnet --version, dotnet --list-sdks and dotnet msbuild -version commands report actual installed tooling.
- Fixed, explicitly approved tasks: SDK/MSBuild versions, offline NuGet restore, C# build, xUnit/NUnit tests and console smoke. Requires trusted local workspace, fresh per-task risk consent, pinned dotnet executable and unchanged project/source/toolchain hashes. No arbitrary user-controlled command flags, shell or project-local SDK execution.
- Build/test happens in an automatically removed temporary project copy using an empty NuGet source list, locally cached package dependencies and offline restore. Tests are allowed only for projects declaring IsTestProject, Microsoft.NET.Test.Sdk and xUnit/NUnit. Temporary output is cleaned, but external code may still write elsewhere.
- The existing separately approved V6 C# LSP and V8 DAP debugger controls remain authoritative; V22 launches neither automatically. The panel pre-fills only the single shared AutoMoto Agent deployment-readiness review, never creating new Agent permissions or deploying.

## Acceptance evidence and tests

- tests/test_developer_dotnet.py: real .NET SDK executable version, MSBuild, offline restore/build, console smoke and deliberate compiler defect, security/access/manifest checks, xUnit and NUnit executable tests, linked manifests, untrusted/hosted denial and source-preservation checks.
- tests/fixtures/v22-console: self-contained .NET 8 console; tests/fixtures/v22-xunit and tests/fixtures/v22-nunit: pinned, real assertion-based test suites.
- .github/workflows/developer-dotnet-v22.yml: cross-platform installed SDK 8/10 matrix on Ubuntu, macOS and Windows. Only GitHub CI prewarms fixed NuGet dependencies with a standard networked restore. AutoMoto itself uses an empty package source list when executing tests.
- apps/desktop/test/ui-smoke.cjs: static C#/ASP.NET/Blazor/NuGet discovery, source integrity and shared Agent review.
- Existing core CI, security, browser, Docker, Office, VS Code, Windows packaging, docs and all prior language acceptance checks must also pass.

## Security limitations

**Build and tests are NOT OS, filesystem or network sandboxed.** MSBuild scripts, NuGet package build targets, compiler extensions, tests and console applications may read credentials, write files outside the copy and access the network as the current local user. Offline NuGet source configuration limits ordinary package fetching, not arbitrary code's network access. Using the local NuGet cache can alter cache contents. File hashes reduce stale-input risks but are not proof against malicious code or all time-of-check/time-of-use races.

V22 supports only a single bounded root C# project for execution. Complex multi-project solutions, generated sources, external MSBuild targets, private feeds, additional resource files, source generators, hosted ASP.NET Core and Blazor runtimes, and other framework test runners are not automatically supported. Razor detection does not certify full web-app builds. Debugging and C# semantic navigation require independently configured approved controls.

## Recovery and release admission

Back up or commit sources before authorising external tools. Restore modified files using the user's VCS/backup. Reverting V22 development commits returns the V1–V21 baseline without modifying the shared Agent or existing workspace state.

Do not declare V22 Verified until exact-head cross-platform CI, real C# LSP and .NET DAP testing, dependency provenance, accessibility, independent security review and human release approval are complete. No merge to main or production publication follows automatically.

## Official references

- .NET SDK CLI: https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet
- NuGet package configuration: https://learn.microsoft.com/en-us/nuget/reference/nuget-config-file
- MSBuild project reference: https://learn.microsoft.com/en-us/visualstudio/msbuild/msbuild
- .NET testing: https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-test
- ASP.NET Core: https://learn.microsoft.com/en-us/aspnet/core/
- Blazor: https://learn.microsoft.com/en-us/aspnet/core/blazor/
