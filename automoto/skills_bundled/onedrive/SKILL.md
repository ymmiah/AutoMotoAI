---
name: onedrive
description: Work with OneDrive / Microsoft 365 files through the Microsoft 365 MCP connector (community).
category: services
connectors: onedrive
status: untested
---
# OneDrive

1. Settings → Connectors → **OneDrive / Microsoft 365** → Enable (`@softeria/ms-365-mcp-server`, community).
   It uses a Microsoft device-code sign-in; follow the link it prints.
2. List or search files, read content, download into the working folder. Writes and sharing ask for approval.
3. Synced OneDrive folder on this computer? Add it in Settings → Files and use read_file/search_files instead - no sign-in needed.
