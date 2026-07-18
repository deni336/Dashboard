# Credentials and external codes

This is the complete inventory of user-supplied external credentials and
companion pairing codes used by Kasugai. Most features do not need a
third-party credential. User-created internal room passwords and
application-generated project invitation links, session secrets, database
encryption keys, and agent tokens are described in the relevant feature or
architecture guide because users do not obtain them from an external provider.
The values below serve different trust boundaries and are not interchangeable.

Never paste a secret into an issue, chat, screenshot, shell command, project
connection URL, or tracked repository file. A project connection is only a
credential-free bookmark; putting a token in its URL is rejected.

## Credential map

| Value | Issuer | Entry point | Purpose |
| --- | --- | --- | --- |
| DeniLicense email and password | Your DeniLicense deployment | Kasugai login page | Authenticate the person signing in |
| DeniLicense claim code | Your DeniLicense administrator | Optional login-page field | Claim an unassigned Kasugai license once |
| Personal OpenAI API key | OpenAI Platform | **Projects → AI model** | Hosted OpenAI requests for one Kasugai user |
| Deployment OpenAI fallback | OpenAI Platform | `OPENAI_API_KEY` or `OPENAI_API_KEY_FILE` | Hosted OpenAI requests for explicitly allowed users without a personal key |
| Private-endpoint API key | Private AI service administrator | `KASUGAI_AI_API_KEY` or `KASUGAI_AI_API_KEY_FILE` | Authenticate to a private/local OpenAI-compatible endpoint |
| Personal GitHub token | GitHub settings | **Settings → Developer** | One user's GitHub identity and unread notifications |
| Deployment GitHub token | GitHub settings or an organization owner | `GITHUB_TOKEN` or `GITHUB_TOKEN_FILE` | Read explicitly allowlisted repository evidence for project AI |
| Gmail app password | Google Account | `KASUGAI_IMAP_PASSWORD` or `KASUGAI_IMAP_PASSWORD_FILE` | Read bounded mailbox evidence for project AI |
| Optional GHCR token | GitHub settings | Operator-side `docker login ghcr.io` | Push an image or pull a private VPS image |
| Workstation pairing code | Kasugai | **Settings → Workstations** | Pair one workstation companion |
| Homelab pairing code | Kasugai | **Settings → Homelab** | Pair one Docker/homelab companion |
| Launcher pairing code | Kasugai | **Settings → Launcher** | Pair one task runner |

## DeniLicense credentials and claim codes

DeniLicense is the identity and license authority for this installation. There
is no universal public Kasugai claim-code site.

### If you are signing in

1. Use the email and password for the DeniLicense service named on Kasugai's
   login page.
2. Leave **Claim Code** blank when a KASUGAI license is already assigned to the
   account.
3. Enter a claim code only when the administrator who operates that DeniLicense
   service issued one to you. Obtain it through that administrator's secure
   delivery channel.
4. Copy the complete code exactly as issued. It is single-purpose and cannot be
   reused after a successful claim. It is also rejected when the underlying
   license is inactive, not yet valid, expired, or revoked. If it fails, ask
   that same administrator to check the code, account type, product, and
   license state.

The login password and claim code are submitted to DeniLicense for the login or
claim operation. They are not settings to place in `.env`.

### If you operate the deployment

Open the browser-reachable DeniLicense origin with `/ui/` appended (for a local
host install, normally `http://127.0.0.1:8080/ui/`). Do not use the
container-only hostname `denilicense-api` in a browser. In the DeniLicense v1.1
console:

1. Open **Products → Create product** and create the exact product code used
   by Kasugai, normally `KASUGAI`.
2. Open **Licenses → Issue license**, select that product and its validity,
   and copy the one-time claim code shown after issuance. Deliver it through a
   secure channel; the user enters it on Kasugai's login page.
3. Alternatively, use **Users → Add user**, choose the `customer` role, and
   send that person the account setup link. A non-customer operator role cannot
   use Kasugai's customer claim workflow.
4. After email verification/password setup, that invited customer—or a person
   who used **Create customer account**—can submit **License requests → Request
   a license** for KASUGAI. A DeniLicense owner or `license_admin` approves the
   request, which assigns the license directly and does not require a claim
   code.

The product code must exactly match `DENILICENSE_PRODUCT_CODE` (normally
`KASUGAI`). Configure:

- `DENILICENSE_API_URL`: the address the dashboard uses to reach the API.
- `DENILICENSE_ISSUER`: the exact logical issuer signed into activation leases;
  this can differ from the network address.
- `DENILICENSE_PRODUCT_CODE`: the licensed product identifier.
- `DENILICENSE_ACTIVATION_LABEL`: the friendly installation label shown by the
  licensing service.

These four values route or identify the integration; none is a password or
claim code. Preserve the dashboard data volume because it contains the generated
installation key and activation lease. Deleting it can consume another seat.

## OpenAI and OpenAI-compatible API keys

No OpenAI account, key, or API billing is required for the optional private
Ollama overlay. Keys are relevant only for the hosted `openai` provider or an
authenticated private OpenAI-compatible endpoint.

### Create a personal OpenAI key

1. Sign in to the [OpenAI Platform API keys page](https://platform.openai.com/api-keys).
2. Select the API project that should own Kasugai usage and billing.
3. Choose **Create new secret key**, name it `Kasugai`, and restrict it to model
   requests/Chat Completions when project controls permit. Kasugai calls
   `POST /v1/chat/completions`; it does not need an organization admin key,
   Files, vector-store, fine-tuning, or administration permissions.
4. Copy it immediately; the full secret is shown only once.
5. In Kasugai, open **Projects → AI model**, paste the key, and save it.

The personal-key control is shown only when the deployment's effective
`KASUGAI_AI_PROVIDER` is `openai`. If the control is absent, ask the operator to
check the provider configuration; creating another key will not reveal it.

The OpenAI API account and billing are separate from a ChatGPT subscription.
Set a project budget and usage alerts before using a key in a shared or
always-on deployment. Kasugai encrypts a personal key in `project_manager.db`,
scopes it to the authenticated Kasugai owner, never returns it after saving,
and uses it ahead of any deployment fallback.

### Configure a hosted deployment fallback

For `KASUGAI_AI_PROVIDER=openai`, prefer a project service-account key for the
shared fallback and set it in `OPENAI_API_KEY_FILE` (preferred) or
`OPENAI_API_KEY`. This name is deliberate: `KASUGAI_AI_API_KEY` is reserved for
the private/local endpoint credential.

An OpenAI organization/project owner can select the project, open
**Organization settings → Project → Members**, choose **+ Service account**,
name it `Kasugai deployment`, and save the API key returned at creation. OpenAI
documents [project service-account management](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform),
[API-key permissions](https://help.openai.com/en/articles/8867743-assign-api-key-permissions),
and the equivalent administrative CLI workflow in
[Create a project, service account, and API key](https://developers.openai.com/api/docs/libraries/openai-cli#create-a-project-service-account-and-api-key).
Treat the returned service-account response as a secret, then narrow the key in
the project's API Keys settings to model requests needed by Chat Completions.

Also configure:

```ini
KASUGAI_AI_PROVIDER=openai
KASUGAI_AI_BASE_URL=https://api.openai.com/v1
KASUGAI_AI_MODEL=<hosted-model-id>
KASUGAI_AI_ALLOWED_USERS=owner-id,owner@example.com
OPENAI_API_KEY_FILE=/run/secrets/kasugai_openai_key
```

The fallback is unavailable to everyone unless their DeniLicense profile ID or
email appears in `KASUGAI_AI_ALLOWED_USERS`. This allowlist gates only the
shared fallback. When the provider is `openai`, an authenticated user can save
and use a personal key regardless of the fallback allowlist; that personal key
takes precedence for that user.

### Configure an authenticated private endpoint

For Ollama or another private OpenAI-compatible service that requires a bearer
credential, use `KASUGAI_AI_PROVIDER=ollama`, obtain the value from that
service's administrator, and set `KASUGAI_AI_API_KEY_FILE` (preferred) or
`KASUGAI_AI_API_KEY`. Keep `OPENAI_API_KEY` empty. Set
`KASUGAI_AI_BASE_URL` to the credential-free API base URL; embedded URL
credentials, queries, and fragments are rejected.

### Rotate or remove an OpenAI key

- Personal key: open **Projects → AI model**, replace or remove it, then revoke
  the old key in the OpenAI Platform.
- Deployment key: revoke it at the provider, replace the secret file, and
  recreate/restart the dashboard container.
- Suspected leak: revoke first. Deleting a leaked string from Git history or a
  ticket does not make the old credential safe.

## GitHub tokens

Kasugai has two separate GitHub integrations. Do not reuse one broadly scoped
token for both unless you have deliberately accepted the larger blast radius.

### Personal notification token

GitHub's notifications REST endpoints require a **personal access token
(classic)**; fine-grained personal access tokens are not supported for this
endpoint. Create the narrow token as follows:

1. Open GitHub's prefilled [new classic token page](https://github.com/settings/tokens/new?scopes=notifications&description=Kasugai),
   or navigate to **Profile picture → Settings → Developer settings → Personal
   access tokens → Tokens (classic)**.
2. Name it `Kasugai`, choose a finite expiration, and select only the
   `notifications` scope. Do not select `repo`, administration, workflow,
   package-write, or deletion scopes just for the notification feed.
3. Generate and copy the token before leaving GitHub.
4. In Kasugai, open **Settings → Developer**, paste it under **Personal access
   token**, and choose **Connect GitHub**.

The Developer settings control is visible only when that user passes
`KASUGAI_DEVELOPER_ALLOWED_USERS`. If it is missing, ask the deployment operator
to review that allowlist; token scope cannot bypass a Kasugai module gate.

Kasugai validates the account through GitHub, encrypts the token in
`personal_dashboard.db`, and never returns it to the browser. It reads the
signed-in user's unread notification feed but does not mark notifications read
on GitHub. Disconnecting removes Kasugai's saved copy; revoke the token in
GitHub as well when it is retired.

GitHub's official [notification endpoint documentation](https://docs.github.com/en/rest/activity/notifications)
and [token-management guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
describe the endpoint restriction, expiration, and revocation workflow.

### Deployment repository-evidence token

Public GitHub repositories can be read without a deployment token. For private
repository evidence, create a separate read-only token. Prefer a fine-grained
token limited to the selected repositories with read access to repository
metadata, contents/commits, and issues. Organization policy may require owner
approval before the token can access organization repositories.

To create it, open GitHub's [fine-grained token settings](https://github.com/settings/personal-access-tokens/new),
select only the intended owner and repositories, choose an expiration, and set
repository permissions **Contents: Read-only** and **Issues: Read-only**
(Metadata read access is implicit). Generate and copy the token once. If an
organization owns the repository, its policy may require an administrator to
approve the token. A classic token fallback needs the broad `repo` scope for
private repositories, so prefer the selected-repository fine-grained token.

Store the result in `GITHUB_TOKEN_FILE` (preferred) or `GITHUB_TOKEN`, then add
only the intended targets to `KASUGAI_GITHUB_TOKEN_ALLOWLIST`:

```ini
GITHUB_TOKEN_FILE=/run/secrets/kasugai_github_source_token
KASUGAI_GITHUB_TOKEN_ALLOWLIST=example/project,example/other-project
KASUGAI_AI_SOURCE_ALLOWED_USERS=owner@example.com
```

Entries are `owner/repository` or `owner/*`. Kasugai sends authentication only
when the project connection points to `github.com`, the owner/repository matches
this allowlist, and the project owner is separately listed in
`KASUGAI_AI_SOURCE_ALLOWED_USERS`. An empty token allowlist means the token is
not sent. An empty source-user allowlist disables all linked-source retrieval.

## Gmail app password for IMAP

Kasugai does not implement Google OAuth. Its project-AI evidence collector logs
in to the configured mailbox over TLS-protected IMAP and performs bounded read
operations. The app password itself is still a sensitive mailbox credential;
do not treat it as harmless or intrinsically read-only.

For a personal Gmail account, IMAP access is already enabled. To create the
credential:

1. Turn on 2-Step Verification for the mailbox's Google Account.
2. Open Google's [App passwords page](https://myaccount.google.com/apppasswords)
   and sign in again if requested.
3. Create an app password named `Kasugai` and copy the generated 16-digit
   value. Enter the generated value, not the normal Google Account password.
4. Configure the full Gmail address and the generated secret:

   ```ini
   KASUGAI_IMAP_HOST=imap.gmail.com
   KASUGAI_IMAP_PORT=993
   KASUGAI_IMAP_USERNAME=owner@example.com
   KASUGAI_IMAP_PASSWORD_FILE=/run/secrets/kasugai_gmail_app_password
   KASUGAI_AI_SOURCE_ALLOWED_USERS=owner@example.com
   ```

5. In the project connection, the nonblank **Account** value must exactly match
   `KASUGAI_IMAP_USERNAME` (comparison is case-insensitive).
6. Restart/recreate the dashboard after changing deployment settings.

Google's [app-password help](https://support.google.com/accounts/answer/185833)
explains eligibility. App passwords can be unavailable for managed accounts,
security-key-only 2-Step Verification, or Advanced Protection. Changing the
Google Account password revokes existing app passwords; generate a replacement
if the mailbox stops working afterward.

## Companion-agent pairing codes

Workstation, Homelab, and Launcher pairing codes come from this Kasugai
dashboard, not an external website:

Each Settings tab is present only when its module is enabled and the signed-in
user passes the corresponding `KASUGAI_WORKSTATION_ALLOWED_USERS`,
`KASUGAI_HOMELAB_ALLOWED_USERS`, or `KASUGAI_LAUNCHER_ALLOWED_USERS` policy. An
absent tab is a deployment-policy issue, not a reason to find a code elsewhere.

1. Sign in as the account that should own the companion.
2. Open the matching Settings tab and choose its **Create pairing** button.
3. From a checkout of this repository on the target Windows computer, run the
   displayed installer command. The Settings page does not download agent
   source files. The pairing ID embedded in the command identifies the pending
   request; it is not the one-time code.
4. When the installer opens a hidden prompt, enter the displayed one-time code.
   Do not append it to the command, because command lines can be retained in
   shell history and process inspection.

Codes expire after ten minutes and can be used once. If one expires, create a
new pairing instead of trying to preserve it. Creating a newer code for the
same owner invalidates the older unused one, and five wrong attempts lock a
pairing. After pairing, the companion
receives a different long-lived agent token and protects it with Windows DPAPI
for the current user. Kasugai never asks the user to copy that long-lived token.

Revoke a companion in its Settings tab if the device is lost or retired. To
move ownership or recover from credential corruption, revoke it and pair again.
See [Companion agents](COMPANION_AGENTS.md) for installation, policy, status,
replacement, and removal details.

## Use secret files in Docker Compose

The nonblank direct environment value wins when both it and its `_FILE`
counterpart are set; a blank direct value permits the file form. Populate only
one nonblank source. Direct `.env` values are convenient for local testing
but can be exposed through environment inspection and copied into generated
Compose configuration. For a shared deployment, mount one file per secret.

Example override:

```yaml
services:
  dashboard:
    environment:
      OPENAI_API_KEY: ""
      OPENAI_API_KEY_FILE: /run/secrets/kasugai_openai_key
      KASUGAI_AI_API_KEY: ""
      KASUGAI_AI_API_KEY_FILE: /run/secrets/kasugai_private_ai_key
      GITHUB_TOKEN: ""
      GITHUB_TOKEN_FILE: /run/secrets/kasugai_github_source_token
      KASUGAI_IMAP_PASSWORD: ""
      KASUGAI_IMAP_PASSWORD_FILE: /run/secrets/kasugai_gmail_app_password
    secrets:
      - kasugai_openai_key
      - kasugai_private_ai_key
      - kasugai_github_source_token
      - kasugai_gmail_app_password

secrets:
  kasugai_openai_key:
    file: ./secrets/openai-api-key.txt
  kasugai_private_ai_key:
    file: ./secrets/private-ai-api-key.txt
  kasugai_github_source_token:
    file: ./secrets/github-source-token.txt
  kasugai_gmail_app_password:
    file: ./secrets/gmail-app-password.txt
```

Keep `secrets/` outside the repository when practical. The checked-in
`.gitignore` excludes a repository-local `secrets/` directory as a second line
of defense, but ignore rules are not access controls. Restrict the files to the
operator account. The dashboard trims surrounding whitespace when reading a
secret file. Recreate the container after changing a file so all integrations
reload predictably.

## Rotation and incident-response checklist

1. Revoke the suspected credential at its issuing provider first.
2. Review provider audit and usage history for unexpected access.
3. Create a replacement with the smallest usable scope, selected resources,
   and a finite expiration.
4. Replace the personal saved value or deployment secret file; recreate the
   dashboard if it is deployment-managed.
5. Confirm the integration works, then remove any remaining saved copy of the
   old value.
6. Remove leaked material from shell history, screenshots, tickets, build logs,
   and Git history. Rotation is still required even if those copies are erased.

Kasugai intentionally does not display stored secrets or agent tokens. A status
of “configured” proves that encrypted material exists; it is not a way to
recover the original value.

## Optional GHCR credential for the VPS image workflow

The standalone Team Room VPS instructions use `KASUGAI_SERVER_IMAGE` and may
point it at GitHub Container Registry (`ghcr.io`). This is a Docker operator
credential, not a Kasugai runtime credential. Do not put it in Kasugai's `.env`
or reuse either GitHub integration token.

- Public GHCR images can be pulled anonymously.
- Pushing needs a personal access token (classic) with `write:packages`.
- Pulling a private image needs a personal access token (classic) with
  `read:packages` and account access to the package.
- Neither operation needs `delete:packages`. Avoid the broad `repo` scope when
  package/repository policy does not require it.

Create the token through GitHub's [Container registry guidance](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
then pass it to Docker through standard input from a protected operator secret:

```powershell
$registryToken = Read-Host "GHCR token" -AsSecureString
$credential = [System.Net.NetworkCredential]::new("", $registryToken)
$credential.Password | docker login ghcr.io -u <github-username> --password-stdin
$credential = $null
$registryToken = $null
```

Use a dedicated read-only pull credential on a private VPS rather than copying
the build machine's write credential. Remove the registry login with
`docker logout ghcr.io` when persistent Docker credential storage is not
intended.
