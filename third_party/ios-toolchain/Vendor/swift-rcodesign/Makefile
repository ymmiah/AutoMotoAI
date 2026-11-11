.PHONY: build test test-without-building lint

build:
	./scripts/build.sh

test: build
	@+$(MAKE) test-without-building

test-without-building:
	cargo test --locked
	swift test

lint:
	swiftlint lint --strict --no-cache Sources Tests Package.swift
	cargo fmt --check
	cargo clippy --locked --all-targets -- -D warnings
