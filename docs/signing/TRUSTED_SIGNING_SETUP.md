# Azure Artifact Signing (formerly Trusted Signing) for the Windows `.exe` and `.msi`

This is the maintainer setup for Authenticode-signing the GitHub `.exe` and `.msi` so Windows no longer shows
**Unknown publisher**. The Microsoft Store copy is already signed by Microsoft and does not use this service.
CI never signs the Store `.msix` / `.msixupload`.

The Windows app workflow (`.github/workflows/desktop.yml`) runs signing only when the secrets and variables
below are present. If they are missing, the job prints a notice and stays green; the direct installers are
just unsigned, as they are today.

## Cost (verified 13 November 2026)

Azure Artifact Signing, formerly Trusted Signing, still uses the Trusted Signing prices:

| SKU | Monthly price | Signatures included | Extra signatures | Certificate profiles |
|---|---|---|---|---|
| **Basic** (recommended here) | **US$9.99** per account | 5,000 / month | US$0.005 each | 1 of each type |
| Premium | US$99.99 per account | 100,000 / month | US$0.005 each | 10 of each type |

Sources: [Artifact Signing product page](https://azure.microsoft.com/en-us/products/artifact-signing)
(Basic US$9.99 / month for 5,000 signatures, then US$0.005; Premium US$99.99 / month for 100,000),
[Change the account SKU](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-change-sku),
and the [pricing page](https://azure.microsoft.com/en-us/pricing/details/artifact-signing/).

Billing starts when you **create the Artifact Signing account**, not when you first sign a file, and the
monthly SKU charge is **not pro-rated**. A typical AutoMoto release signs a handful of files (the app
executable, the NSIS installer, the MSI), so Basic is enough.

The service also needs a **paid** Azure subscription (pay-as-you-go or enterprise). It does **not** work
on free, trial or sponsored subscriptions. —
[Artifact Signing FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq#can-i-use-artifact-signing-with-a-free-trial-or-sponsored-azure-subscription)

## Public Trust identity: UK eligibility (verified 13 November 2026)

This matters if you are setting this up as an individual in the United Kingdom.

Microsoft's current rule is:

> Public Trust certificates are available to **organizations** in the United States, Canada, the European
> Union, **the United Kingdom**, Australia, New Zealand, Japan, South Korea, Singapore, Switzerland,
> Norway, and Israel. **Individual developers must be located in the United States or Canada.**

Source: [Quickstart: Set up Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
The same limit is stated in
[Code signing options for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).

So, today:

* **Individual Public Trust** (your own name on the certificate, using UK details) is **not available**.
  The portal will reject it if the billing account country is the United Kingdom.
* **Organization Public Trust** **is** available in the United Kingdom, if you have a registered organisation
  and complete organisation identity validation. The Azure billing account used for that request must be an
  **Organization** account, not an Individual account.
* **Private Trust** certificates have no such country limit, but they are not trusted by Windows as a public
  publisher and will not fix SmartScreen for public GitHub downloads.

Until Public Trust is in place, keep pointing people at the [Microsoft Store listing](https://apps.microsoft.com/detail/9N9J7FLSSFG8).
That copy is signed by Microsoft. The GitHub `.exe` / `.msi` can stay as advanced direct installers.

If individual validation is later opened to the UK, the same CI wiring still applies; only the Azure identity
step changes. Microsoft has said EU/UK individual onboarding is planned, with no date.

## 1. Azure subscription

1. Sign in to the [Azure portal](https://portal.azure.com) with the Microsoft account that should own this.
2. Confirm the subscription **Offer** is pay-as-you-go or an enterprise agreement, not a free trial or
   sponsorship. Upgrade first if it is still a free offer.
3. Register the resource provider: **Subscriptions → (your subscription) → Resource providers →
   `Microsoft.CodeSigning` → Register**.

## 2. Create an Artifact Signing account

1. In the Azure portal, create an **Artifact Signing** account (the resource may still be labelled
   **Trusted Signing** in some blades).
2. Put it in a region the service supports. For a UK-based publisher, **North Europe** or **West Europe**
   is the usual choice.
3. Choose the **Basic** SKU unless you later need a much higher signing quota.
4. Note the **endpoint** for that region. It must match the account region or signing fails with 403:

   | Region | Endpoint |
   |---|---|
   | North Europe | `https://neu.codesigning.azure.net/` |
   | West Europe | `https://weu.codesigning.azure.net/` |

   The full region list is in
   [Set up signing integrations](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations).

## 3. Identity validation

1. On the account, open **Identity validations**. You need the **Artifact Signing Identity Verifier** role
   (and at least Reader on the subscription).
2. Start a **Public** identity request:
   * **Organization**, if you have a UK-registered organisation (this is the supported Public Trust path
     in the UK).
   * **Individual**, only if you are in the United States or Canada.
3. For an individual request, Azure fills the form from the subscription's billing account. The billing
   account type must be Individual, and the legal name and sold-to address must match the government ID
   you will use.
4. When the status is **Action Required**, complete the verification link. Wait until the status is
   **Completed** before creating a certificate profile. This can take a few business days.

## 4. Public Trust certificate profile

1. On the account, open **Certificate profiles → Create**.
2. Choose **Public Trust** (not Public Trust Test, and not Private Trust, for files you ship to users).
3. Give it a short, stable name, for example `automoto-public`. You will put that name in a GitHub variable.
4. The subject on the certificate is the validated legal name. You cannot set a custom CN.

## 5. App registration and the Signer role

CI signs as an app, not as your login.

1. In **Microsoft Entra ID → App registrations**, create an application (for example `automoto-artifact-signing`).
2. Note the **Directory (tenant) ID**, **Application (client) ID**, and the subscription ID.
3. Preferred: add **Federated credentials** for GitHub Actions OIDC so there is no long-lived secret:
   * Issuer: `https://token.actions.githubusercontent.com`
   * Audience: `api://AzureADTokenExchange`
   * Subject for builds on `main`: `repo:ymmiah/AutoMotoAI:ref:refs/heads/main`
   * Subject for a release tag: `repo:ymmiah/AutoMotoAI:ref:refs/tags/v5.6.0` (add one credential per
     tag, or use the client-secret fallback for tags). Entra does not reliably accept a tag wildcard.
   * Alternative that covers both: create a GitHub Environment named `trusted-signing` (no required
     reviewers) and one federated subject `repo:ymmiah/AutoMotoAI:environment:trusted-signing`, then
     we can point the Windows job at that environment later.
   The workflow only attempts signing on `main`, on `v*` tags, and on a manual *Windows app* run.
   Pull requests skip signing with a notice, so a missing OIDC subject cannot fail CI.
4. Optional fallback: create a **client secret** and store it as `AZURE_CLIENT_SECRET`. That works on
   `main`, tags and manual runs without extra federated subjects. Treat it as a password; it expires
   and must be rotated.
5. On the Artifact Signing account (or the certificate profile), assign the app the role
   **Artifact Signing Certificate Profile Signer**. Older docs and some blades still say
   **Trusted Signing Certificate Profile Signer**; it is the same role after the rename. —
   [Assign roles in Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/tutorial-assign-roles)

If you use a GitHub Environment (`trusted-signing`), add the federated subject
`repo:ymmiah/AutoMotoAI:environment:trusted-signing` and, later, we can pin the signing steps to that
environment. The workflow as merged can use repository secrets and OIDC at the job's default scope.

## 6. GitHub secrets and variables

In the AutoMotoAI repository: **Settings → Secrets and variables → Actions**.

**Secrets:**

| Secret | What it is |
|---|---|
| `AZURE_TENANT_ID` | Directory (tenant) ID |
| `AZURE_CLIENT_ID` | Application (client) ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription ID (needed for `azure/login`) |
| `AZURE_CLIENT_SECRET` | Client secret, **only** if you are not using OIDC |

**Variables:**

| Variable | Example |
|---|---|
| `TRUSTED_SIGNING_ENDPOINT` | `https://neu.codesigning.azure.net/` or `https://weu.codesigning.azure.net/` |
| `TRUSTED_SIGNING_ACCOUNT` | the Artifact Signing / Trusted Signing account name |
| `TRUSTED_SIGNING_PROFILE` | the Public Trust certificate profile name |

After these exist, the next `Windows app` run on `main` or a `v*` tag signs `AutoMoto AI.exe`, then the
NSIS `.exe` and the `.msi`, then writes the Tauri updater `.sig` files and `SHA256SUMS.txt` for those
final signed files. The Store package is still uploaded unsigned. New signatures still need time and
downloads before SmartScreen reputation builds; signing does not skip SmartScreen on the first release. —
[SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)

## 7. What this does not replace

* **Microsoft Store** stays the recommended Windows install. Microsoft signs that package.
* **Tauri updater signatures** (`TAURI_SIGNING_PRIVATE_KEY`) are separate: they prove an update came from
  this repo. Authenticode is what Windows uses for "publisher".
* **SignPath Foundation** is not used. Its free certificates require an OSI-approved licence without a
  commercial licence option, and AutoMoto is AGPL-3.0-only plus a commercial licence.
