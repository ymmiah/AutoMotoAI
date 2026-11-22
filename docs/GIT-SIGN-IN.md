# Connect GitHub or GitLab (sign-in and keychain)

Developer Studio can sign in to **GitHub** (github.com) and **GitLab** (gitlab.com or your own GitLab
server) so it can share your work in a later version. This page covers what the sign-in does, where your
token is kept, and how to turn it off. It doesn't push or open pull requests yet. Those come in later
pull requests from the V46–V48 plan, and they will always ask you first.

## Sign in, in 3 steps

Open **Developer Studio → Tools → Connect GitHub or GitLab**. On a phone or tablet, use the **Tools** tab.

1. **Choose where your code lives.** Pick GitHub or GitLab. For your own GitLab server, open
   **Use your own GitLab server** and type its address, for example `gitlab.example.com`. It must be https
   and a public address. Tokens are only ever sent to servers on this list.
2. **Make a token.** **Open the token page** goes to the provider with the least access already filled in:
   - **GitHub (fine-grained token):** Contents read and write, Pull requests read and write, Commit
     statuses read-only, Actions read-only, plus Metadata read-only, which GitHub always adds. Under
     Repository access, choose **Only select repositories**. Keep the 30-day expiry.
     Workflows, Administration, Secrets and Webhooks aren't needed.
   - **GitLab (personal access token):** `read_user`, `read_api` and `write_repository`. Pick an expiry about
     30 days away. `api` isn't needed now. It will only be asked for later, if you want to ask for a review.
   The address has a copy button if you'd rather open it yourself.
3. **Paste it here** and press **Connect**. The field is masked and emptied the moment you press Connect.

AutoMoto checks the token with the provider and shows:

- **Connected as @you**, the provider and the server
- **Ends**: the expiry date and how many days are left
- **Access**: the scopes the token has (GitHub fine-grained tokens keep their permissions on GitHub)
- **Saved in**: Windows Credential Manager, macOS Keychain or your Linux keyring
- **Token**: only the last four characters, for example "ends in 4f2a"

You also get a warning if the token is too broad or unsafe:

- a **classic** GitHub token (`ghp_…`), which can reach every repository you can
- scopes such as `repo`, `workflow`, `delete_repo`, `admin:*` on GitHub, or `api`, `sudo`, `admin_mode` on GitLab
- a token that **never expires**, or one that lasts more than a year

## Where your token is kept

- **Only in your computer's password store** (the OS keychain): Windows Credential Manager, the macOS
  Keychain, or Secret Service/libsecret on Linux. The entry is called "AutoMoto AI Git", one per
  provider and server.
- **Never** in files or `.env`, Git settings, remote URLs, logs, browser storage (localStorage,
  sessionStorage, cookies) or the page itself. The app's screens only ever get the masked handle.
- **No password store?** Some Linux setups don't have one. AutoMoto then asks before keeping the token
  in memory only. It is gone when AutoMoto closes, and nothing is written to disk.
- The token is only sent to the provider's API on the server you chose: `api.github.com`, `gitlab.com`, or
  your own server. Every request goes through an exact-host allowlist, and redirects to anywhere else are refused.
- Logs, error messages and tool output are scrubbed of anything that looks like a token. That includes partial
  tokens (`ghp_abcd…`), URL-encoded or base64 forms, and a token cut across two lines.

## Tokens already in a `.env` file

If `GITHUB_TOKEN`, `GH_TOKEN` or `GITLAB_TOKEN` is in a `.env` file, the page says so and offers
**Move it to the password store**. With your OK, AutoMoto checks the token, saves it in the keychain and
deletes that line from the `.env` file. Other lines are left alone. A token set as a system environment variable
can't be removed by AutoMoto, so the page tells you to remove it yourself.

A project's own `.env` can no longer change where tokens are sent. `GITLAB_URL` is only read from a real
environment variable or `~/.automoto/.env`, and its server must be on your allowed list.

## Sign out, expiry and turning a token off

- **Sign out** removes the token from this computer. The page then links to the provider's tokens page so
  you can turn the token off everywhere:
  - GitHub fine-grained tokens: <https://github.com/settings/personal-access-tokens>
  - GitHub classic tokens: <https://github.com/settings/tokens>
  - GitLab: `https://<your server>/-/user_settings/personal_access_tokens`, then **Revoke**
- **Sign out everywhere on this computer** removes every GitHub and GitLab sign-in.
- **Check again** asks the provider if the token still works. If the provider says it expired or was deleted,
  AutoMoto removes it from the keychain and asks you to make a new one. The same happens on its own when the
  expiry date passes.

## Browser sign-in (off unless set up)

The code also includes the GitHub **device flow** and GitLab **authorization code + PKCE** (with the
device grant as a fallback). They are **switched off** because they need a registered app. If you ever
register one, put only its public client ID in a real environment variable or `~/.automoto/.env`:

```
AUTOMOTO_GITHUB_CLIENT_ID=Iv23li...
AUTOMOTO_GITLAB_CLIENT_ID=<application id>
```

No client secret is used or stored. A client ID in a project's `.env` is ignored. Without a client ID, the
token steps above are the only way in.

## For developers

- Engine: `automoto/git_auth.py` (vault, validation, migration, flows, audit log) and
  `automoto/redaction.py` (pattern and known-secret redaction, installed on every log record). The API lives
  under `/api/developer/studio/account/*`, needs the local session and isn't available in hosted mode.
  Bodies are parsed by hand so a validation error can't echo a token back, and every answer is checked for
  the token before it's sent.
- UI: `automoto/web/static/developer-account.js` (no browser storage; the field is cleared on submit).
- The agent's `service_api` tool uses the signed-in GitHub/GitLab account first. Plaintext `.env` tokens still
  work for it, so nothing breaks, but browser tab keys are ignored for GitHub and GitLab.
- Audit log: `~/.automoto/git-auth-audit.jsonl` (sign-in, sign-out, expiry, migration, never a token).
- Tests: `tests/test_git_auth.py` and `apps/desktop/test/git-signin.cjs`.
