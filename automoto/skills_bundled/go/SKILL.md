---
name: go
description: Write, build and test Go programs - modules, packages, errors, goroutines, cross-compiling.
category: coding
tools: write_file, edit_file, run_app
apps: go
status: live
---
# Go

- Start: `run_app` `go` `["mod", "init", "example.com/app"]`; code in `main.go` or `cmd/app/main.go`, packages in folders.
- Run/test/vet: `["run", "."]`, `["test", "./..."]`, `["vet", "./..."]`, format with `["fmt", "./..."]` (or `gofmt -l .`).
- Errors: return `error` values, wrap with `fmt.Errorf("doing x: %w", err)`, check with `errors.Is/As`. No panics for normal errors.
- Tests: `_test.go` files, table-driven tests with `t.Run`, `t.TempDir()`, `go test -race ./...` for concurrency.
- Concurrency: goroutines + channels or `sync.WaitGroup`; always cancel with `context.Context`; protect shared maps with `sync.Mutex`.
- Cross-compile (all OSes): set env per build, e.g. in `run_shell`:
  `GOOS=windows GOARCH=amd64 go build -o dist/app.exe .`, `GOOS=darwin GOARCH=arm64 go build -o dist/app-mac .`,
  `GOOS=linux GOARCH=amd64 go build -o dist/app-linux .` (pure Go; cgo needs a cross C toolchain).
- Dependencies: `["get", "pkg@version"]`, then `["mod", "tidy"]`.
