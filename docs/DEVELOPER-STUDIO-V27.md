# Developer Studio V27/64 — Ruby, Lua, Perl & Groovy

**Development-only milestone.** Builds on the fully merged and CI-green V26 cumulative development baseline. No production, `main`, package publication or cloud execution.

## Delivered

### Non-executing project intelligence
- Authenticated, bounded local inspection of Ruby (`.rb`), Lua (`.lua`), Perl (`.pl`, `.pm`, `.t`) and Groovy (`.groovy`, `.gvy`, `.gy`). Each source is hashed, statically inspected for declarations, pattern-based risk signals and missing final newline, overlong lines, trailing whitespace or leading tabs.
- **Package manifests are read, not evaluated.** Inspects root `Gemfile` and lockfile, root Ruby gemspec and Rakefile, LuaRocks `.rockspec`, `cpanfile` and CPAN metadata, Gradle `build.gradle` and associated configs. Reports literal-looking gem, rock, Perl module and Groovy dependency declarations. Regex-based metadata can miss dynamic dependencies, branch-dependent sources, macros and environment-driven behavior. Never presents that inventory as an authoritative resolved dependency graph.
- Installed `ruby`, `gem`, `bundle`, `rubocop`, `lua`, `luac`, `luarocks`, `luacheck`, `perl`, `cpanm`, `perltidy`, `perlcritic`, `groovy`, `groovyc`, `gradle` and `codenarc` are discovered and fingerprinted by exact executable path and SHA-256. Inspection does not execute version probes, invoke dependency installers, bootstrap Java or run formatters.
- The Studio shows the per-language source/manifest inventory, SHA-256 status, available tools, static style advice and risk signals, without modifying files.
- Every executable operation requires an authenticated *local* API request, user-trusted project, exact source/toolchain fingerprints, fixed command and explicit per-run risk acceptance. The approved project is copied into a bounded private temporary working directory, its stage source bytes revalidated with no-follow reads, and command output/duration limited. Original sources are not intentionally edited.

### Approved executable adapters
| Language | Version & package view | Syntax/compile | Canonical test | Lint/format status |
| --- | --- | --- | --- | --- |
| Ruby | Installed `ruby/gem/bundle` versions on explicit request; Gemfile metadata. Optional `bundle check` requires Gemfile **and** lockfile. | `ruby -c` | `ruby -Ilib test/fixture_test.rb` | External RuboCop `--format simple --force-exclusion` only when installed and approved; read-only whitespace hints. No autoformat or rewriting. |
| Lua | Installed `lua/luac/luarocks` versions; static LuaRocks declarations. | `luac -p` | `lua test/fixture_test.lua` | Installed Luacheck `--no-config --no-color` if explicitly consented; read-only formatting hints. |
| Perl | Installed `perl/cpanm/perltidy/perlcritic` versions; static cpanfile declarations. | `perl -c` (**may execute BEGIN blocks**) | `perl -Ilib test/fixture_test.t` | Installed perltidy/perlcritic discovery, plus read-only formatting hints; no unreviewed formatter execution. |
| Groovy | Installed `groovy/groovyc/gradle/codenarc` versions; literal-looking Gradle dependency inventory. | `groovyc -d <temporary folder>` (**AST transforms may execute code**) | `groovy -cp <temp lib> test/FixtureTest.groovy` | CodeNarc discovery, read-only style hints; no automatic formatter/Gradle plugin execution. |

The Studio does **not** allow arbitrary test paths, arguments, `-e` or script templates; only the four canonical fixture paths may run. Test scripts themselves are still executable user-owned code, not a safe subset language. Ruby Bundler checks evaluate the Gemfile and can execute arbitrary code; user confirmation and trust are mandatory. Ruby/Lua external lints may load plugins/configuration; approval does not establish OS isolation.

### Real acceptance evidence
- `tests/fixtures/v27-scripting/`: independent Ruby 42 arithmetic, Lua 42 arithmetic, Perl `Test::More`, Groovy 42 arithmetic fixtures with explicit `V27_*_FIXTURE_PASS` markers, plus a Ruby malicious-command source and a Perl `BEGIN` trap that must never run during inspection.
- `tests/test_developer_scripting.py`: verifies all four languages and declared packages in inert inventory; unchanged original bytes, startup-hook risk signaling, auth and hosted denial, exact SHA consent, unknown task and arbitrary script path denial, missing Gemfile lock refusal and source symlink rejection. Installed-tool CI runs version, syntax/compile and canonical fixture tests and checks stable output markers with no package installation.
- `.github/workflows/developer-scripting-v27.yml`: Windows/macOS/Linux inert API/security regression, real Ruby/Lua/Perl/Groovy compilers and tests on Ubuntu, Ruby/Lua/Perl tests on macOS, and installed Ruby interpreter/tests on Windows. Tool install occurs only in isolated CI environments. Exact runner images, availability and all-green evidence must be verified after the PR runs.
- `apps/desktop/test/ui-smoke.cjs`: browser inspection of Ruby/Lua/Perl/Groovy, package metadata and malicious Ruby risk, unchanged source bytes and the **same central AutoMoto Agent** release-review draft. No Agent action is automatically submitted.

## Threat model and limitations

**The tool runners are NOT an OS-level filesystem or network sandbox.** `ruby`, `perl`, `groovyc`, Bundler, linters and test scripts run as the local user, potentially accessing secrets, processes and the network, or changing paths outside the temporary copy. Perl's `-c` can run `BEGIN` blocks; Groovy compilation may run AST transformations and extensions. Do not run untrusted code even if it is labelled “syntax only”. The staging/hash checks are change-detection measures, not a guarantee of security against all races, runtime attacks or toolchain supply-chain compromise.

No dependency installation, automatic `gem install`, `bundle install`, LuaRocks, CPAN or Gradle dependency resolution occurs by default. `bundle check` is a separately authorised local task and can evaluate Ruby Gemfile code. No plugin download, RubyGems publishing, package uploads or application deployment.

Optional RuboCop/Luacheck are advisory checkers; their absence is displayed as unavailable. Perl perltidy and Groovy CodeNarc are only fingerprinted/discovered, not claimed as active automatic formatters. Manual configuration of these tools and more capable dependency lockfile provenance are future engineering work, not certification delivered by V27.

No autonomous change from the Agent is introduced: `deployment_readiness` is populated as a **draft** in the existing single central AutoMoto Agent and requires independent user action and approval.

## Recovery and quality gates

Commit/back up the approved workspace before any external task. Only execute reviewed local sources and toolchains. If code executed as part of an approved task changes host state, restore through version control, backups and operating-system controls. Reverting V27 commits on the development branch preserves V1–V26 and user data.

V27 remains **Review** pending exact-head four-language acceptance, UI/core CI, Windows packaging, manual interpreter/formatter/provenance and supply-chain review, accessibility and human approval. A successful test fixture does **not** verify a full language runtime, complex Gradle app, dependency graph or general-purpose unsafe script.

Official references: [Ruby](https://www.ruby-lang.org/en/documentation/) · [RubyGems](https://guides.rubygems.org/) · [Lua 5.4](https://www.lua.org/manual/5.4/) · [LuaRocks](https://luarocks.org/) · [Perl](https://perldoc.perl.org/) · [Groovy](https://groovy-lang.org/) · [Gradle](https://docs.gradle.org/current/userguide/userguide.html).
