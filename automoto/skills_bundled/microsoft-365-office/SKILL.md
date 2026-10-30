---
name: microsoft-365-office
description: Work with Word, Excel and PowerPoint files in OneDrive/SharePoint through Microsoft Graph with your own access token - list, download, upload and edit workbooks - or use free desktop alternatives.
category: office
tools: service_api, read_file, office_create_docx, office_create_xlsx, office_create_pptx
optional_apps: libreoffice
status: untested
---
# Microsoft 365 (Word, Excel, PowerPoint online)

**Free route (default)**: AutoMoto builds and checks real .docx/.xlsx/.pptx files locally with the
office tools and LibreOffice (free, open source). They open in Microsoft Word/Excel/PowerPoint,
Office on the web (free with a Microsoft account), LibreOffice, OnlyOffice (free desktop editors,
optional) and Google Docs. Microsoft Office itself is not required.

**Microsoft Graph (BYOK, files only)**
- The user creates a token with Files.ReadWrite scope (e.g. Graph Explorer → Access token) and adds it as the
  `msgraph` key in Settings (tab-only) or `MS_GRAPH_TOKEN` in .env. Never paste tokens into chat.
- List: `service_api service=msgraph path=/v1.0/me/drive/root/children`.
- Search: `path=/v1.0/me/drive/root/search(q='report')`.
- Excel workbook API: `path=/v1.0/me/drive/items/ITEM_ID/workbook/worksheets`, read a range with
  `.../worksheets/Sheet1/range(address='A1:D10')`; updates use PATCH and need approval.
- Mail, Teams, calendars, contacts, users/directory, sharing links and invitations are **blocked** -
  AutoMoto never sends or shares anything for the user.
Status: untested against a live Microsoft 365 tenant (needs the user's token).
