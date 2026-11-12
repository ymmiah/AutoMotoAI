package = "automoto-v27"
version = "1.0-1"
source = { url = "https://example.invalid/v27.tar.gz" }
description = { summary = "V27 static LuaRocks metadata" }
dependencies = { "lua >= 5.1" }
build = { type = "builtin", modules = { ["v27"] = "lib/v27.lua" } }
