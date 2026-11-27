@echo off
rem zg MCP stdio entry shim.
rem Why: DSH spawns stdio MCP servers through `cmd /d /s /c` on Windows and quotes
rem every argument separately, so `server` arrives as the literal '"server"' and zg
rem answers `Unknown command: "server"` -> the client reconnects forever.
rem Keep subcommand+flags inside this shim and configure command = "zg-mcp" with no args.
zg server --stdio --mcp-toolset full %*
