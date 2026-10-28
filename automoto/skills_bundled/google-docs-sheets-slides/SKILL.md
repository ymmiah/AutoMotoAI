---
name: google-docs-sheets-slides
description: Read and update Google Docs, Sheets and Slides through Google's official REST APIs with your own OAuth access token - or build locally and import into Google Drive.
category: office
tools: service_api, office_create_docx, office_create_xlsx, office_create_pptx
status: untested
---
# Google Docs, Sheets and Slides

Two routes - prefer the first unless the user needs live collaboration in Google:

**A. Build locally, upload to Drive (free, no token needed by AutoMoto)**
Create the .docx/.xlsx/.pptx with the office tools, check it, then tell the user to upload it to
Google Drive (it converts to Docs/Sheets/Slides on open) or use the google-drive skill / connector.

**B. Official APIs (BYOK OAuth access token)**
- The user gets a short-lived access token with the right scopes (documents, spreadsheets,
  presentations - e.g. from the OAuth 2.0 Playground or their own OAuth client) and adds it as the
  `google-docs` / `google-sheets` / `google-slides` key in Settings (kept in this browser tab only) or as
  `GOOGLE_ACCESS_TOKEN` in .env. Never ask them to paste it into chat.
- Read: `service_api service=google-docs path=/v1/documents/DOC_ID`;
  `service=google-sheets path=/v4/spreadsheets/ID/values/Sheet1!A1:D20`;
  `service=google-slides path=/v1/presentations/ID`.
- Write (asks for approval): `POST /v1/documents/ID:batchUpdate` with `requests` (insertText,
  replaceAllText…); Sheets `PUT /v4/spreadsheets/ID/values/RANGE?valueInputOption=USER_ENTERED`;
  Slides `POST /v1/presentations/ID:batchUpdate`.
- Sharing and permission changes are blocked - the user shares files themselves.
Status: untested against live Google accounts (needs the user's OAuth token).
