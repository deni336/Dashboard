# User guide

This guide explains the workflows available after Kasugai is installed. Which
sections you see depends on the deployment's DeniLicense entitlements, enabled
modules, and user allowlists. A missing control is often an operator policy, not
a browser problem.

## Sign in and activate access

Use the email and password for the DeniLicense service named on the login page.
Kasugai sends those values to that service for authentication; it does not
create a separate local password.

- If an active KASUGAI license is already assigned to your customer account,
  leave **Claim Code** blank.
- If the DeniLicense operator issued a claim code, enter the complete code in
  the optional field during login.
- Do not search GitHub, OpenAI, or a public Kasugai site for a claim code. It
  comes only from the operator of the displayed DeniLicense service.

See [Credentials and external codes](CREDENTIALS.md) when you need an account,
claim code, personal GitHub token, or personal OpenAI key.

Signing out removes the browser session. It does not revoke your DeniLicense
account, personal provider credentials, project shares, or paired agents.

## Find your way around

Home is the Developer Cockpit. The page is divided into numbered modules and a
top bar with:

- command palette/quick navigation;
- Team Room;
- Unified Nerd Inbox;
- Settings;
- sign out.

Press **Ctrl+K** on Home to open the Universal Launcher search. It combines
known dashboard destinations, configured HTTPS shortcuts, permitted repository
destinations, and tasks published by your paired Launcher agent. Searching does
not execute a task; a run still passes server and local policy gates and may
open a confirmation preview.

Projects is a separate portfolio workspace. Both Home and Projects open the
same Team Room drawer, so closing the drawer does not discard the current page.

## Projects

### Create a project

1. Open **Projects**.
2. Choose the **New project** button.
3. Supply a name and a 2–16 character code. The code starts with a letter or
   number, can contain letters, numbers, `_`, or `-`, and is saved uppercase.
4. Optionally set status, priority, health, manager, sponsor, dates, budget,
   progress, and description.
5. Save the project.

Project codes need to be unique only inside your own portfolio. Another owner
can use the same code. Use the project search to filter your portfolio and
select a card to open its detail view.

### Maintain the project brief

The overview keeps delivery and governance information together:

- **Project brief**: status, priority, health, progress, dates, budget,
  manager, sponsor, and description.
- **Upcoming work**: task and milestone due dates.
- **Meeting log**: attendees, notes, decisions, action items, and next steps.
- **RAID and decisions**: risks, assumptions, issues, dependencies, and
  decisions.
- **Stakeholder register**: role, email, influence, engagement, and notes.
- **Connections**: reusable or project-specific bookmarks.

Project control items use one shared editor. Choose the type first, then set its
title, state, priority/impact, owner, due date, details, and response/rationale.
Use a decision record for a decision that should remain discoverable rather
than burying it only in meeting notes.

### Add connections safely

A connection is a validated bookmark, not an OAuth connector. Choose a
provider, project/global scope, label, optional Account, and URL.

- Never paste a password, personal access token, API key, OAuth secret, or
  credential-bearing URL into Account or URL.
- Kasugai rejects URL user-info such as `https://user:password@example.com`.
- A global connection appears across your portfolio; project scope limits it to
  the selected project.
- Connections remain private to their owner except project-scoped links made
  visible through the shared project workspace.

GitHub and Gmail connections can identify evidence sources for Ask Kasugai, but
the provider credential is deployment-managed. For Gmail, the Account value
must match the mailbox configured by the operator. Other provider types remain
bookmarks; adding one does not authorize Kasugai to read that service.

### Share a project

Only the owner can share or delete a project.

1. Open **Share project**.
2. Enter the recipient's exact email address.
3. Select **Viewer** or **Editor**.
4. Create the invitation.
5. Copy the one-time link, or choose **Email invitation** to open your system
   mail client with a prepared draft.

Kasugai does not run an SMTP sender. You are responsible for delivering the
link securely. The invitation is valid for seven days and is bound to the
invited email. The recipient must sign in to Kasugai with that exact email and
have their own valid DeniLicense access.

| Role | Read | Edit project content | Share/delete project | See owner's unrelated/global secrets |
| --- | --- | --- | --- | --- |
| Viewer | Yes | No | No | No |
| Editor | Yes | Yes | No | No |
| Owner | Yes | Yes | Yes | Own data only |

The owner can change a collaborator's role, revoke access, or issue a new
pending invitation. Treat an invitation URL as a temporary secret until it is
accepted or expires. If it is exposed, revoke/reissue it rather than editing the
URL.

### Use Ask Kasugai

Ask Kasugai is a preview-and-apply assistant. It never silently writes project
changes.

1. Open a project and choose **Ask Kasugai**.
2. Select an existing conversation or start **New chat**.
3. Review the disclosure: it names the configured backend/model and whether
   live readiness is confirmed.
4. Enter a bounded question or update request.
5. Leave GitHub/email evidence selected only when those project connections are
   relevant and the operator has enabled source retrieval.
6. Generate a preview.
7. Read the answer, warnings, citations, and every proposed action.
8. Select only the actions you intend to make and choose **Apply selected
   changes**.

Proposals can update supported project fields, create/update control records,
or create meeting records. They cannot delete data. A proposal is signed,
expires after 15 minutes, and is rejected if the project or target records have
changed since the preview. Regenerate after a conflict instead of forcing an
old plan over newer work.

Source text is treated as untrusted evidence and is bounded before inference.
The model has no direct browser, filesystem, database, shell, Git, or provider
tool. It returns a structured proposal to Kasugai; the user decides what to
apply.

When the deployment uses hosted OpenAI, the **AI model** control lets you save a
personal project API key. The full key is never shown again. API billing is
separate from a ChatGPT subscription. The control is absent for the private
`ollama` provider because local/private credentials are configured by the
operator, not each user.

## Team Room

Open Team Room from Home or Projects. Join or create a room before using chat,
file transfer, or screen sharing.

### Rooms and chat

- Create a room with the intended name and optional room password.
- Share the room name/password directly with participants.
- Join before sending messages or opening the room's collaboration controls.
- Closing the drawer hides the collaboration surface but does not call the Go
  service's leave-room operation; the current dashboard has no separate Leave
  control.

A room password is chosen by a user; it is not an external access code. It is a
light room control, not a substitute for a trusted network. The current Team
Room service keeps users, rooms, messages, pending file bytes, and media state
in memory. A Go service restart clears them, so use Projects or another durable
system for records that must survive a restart.

### Files

Choose a file from the Team Room transfer area and offer/send it to the current
room. Recipients use the room's file history/offer controls to receive it. The
dashboard route limits a transfer to 100 MiB; an operator's reverse proxy may
set a smaller limit.

Treat received files as untrusted. Kasugai transfers bytes; it does not provide
malware scanning or attest that a sender's file is safe.

### Screen sharing

Expand the Team Room screen-sharing area, choose the appropriate browser share
source, and stop sharing when finished. Browser permissions and the separate
media service must both be available. The compatibility `/screenshare` link
opens this same drawer with that area expanded; it is not a second application.

## Developer Cockpit

### Repositories

The repository cards show bounded status such as branch and change/sync counts.
Favorite or filter the repositories you use most. Kasugai runs a fixed,
non-interactive read-only Git inspection set; it does not show changed filenames
or accept arbitrary Git commands.

If no repositories appear, the operator must allow a server-visible root. The
standard container deliberately has no host source mount.

### GitHub notifications

When the Developer module is available:

1. Open **Settings → Developer**.
2. Follow the inline helper to create a GitHub personal access token (classic)
   with only `notifications`.
3. Connect it and verify the shown GitHub identity.

Kasugai reads the unread notification feed. Inbox actions such as archive or
mark-read change only Kasugai's local overlay; they do not mutate GitHub. Use
**Disconnect GitHub** and revoke the token at GitHub when retiring it.

### Quick-launch shortcuts

Settings lets you create named HTTPS shortcuts. Keep them credential-free. A
shortcut opens in the browser only after you select it; the dashboard does not
fetch the target server-side.

## Workstation Monitor

The Workstation card shows aggregate telemetry sent by your paired outbound
Windows agent: CPU, memory, supported GPU, fixed disk, network rates, uptime,
and battery where available.

It does not collect filenames, command lines, usernames, IP/MAC addresses,
ports, environment variables, browser history, or per-process details. Rename
or revoke your paired computers in Settings. Pairing and local diagnostics are
covered in [Companion agents](COMPANION_AGENTS.md).

## Docker & Homelab

The Homelab dashboard can show locally opted-in containers and locally defined
HTTP health checks. The browser cannot add a target, enable inventory, or grant
logs/restart access.

An action is available only when all layers agree:

- the deployment module/owner policy;
- the server action kill switch;
- the host's local JSON policy;
- current container labels;
- the fixed requested operation;
- confirmation where required.

Read a log excerpt only when you understand that logs can contain application
data. Confirm restart only for the displayed opted-in container. There is no
browser protocol for exec, shell, stop, delete, prune, pull, paths, custom
signals, or arbitrary arguments.

## Universal Launcher

The Launcher catalog contains presentation metadata and opaque task IDs
published by your paired Windows runner. The executable, arguments, working
directory, timeout, and approval policy stay on that computer in local JSON.

1. Search with **Ctrl+K** or use the Launcher module.
2. Select a task.
3. Read the confirmation preview when one is required.
4. Queue it only if the task/runner are the intended target.
5. Review the bounded status/output summary.

The browser cannot alter the command. Revoke a lost/retired runner in Settings.
See [Companion agents](COMPANION_AGENTS.md) before publishing local tasks.

## Automation Engine

Open **Settings → Automation** to create a rule. Give it a clear name, choose
one trigger, choose one fixed action, set a cooldown, and decide whether it
starts enabled.

Trigger types:

- interval;
- daily time in the dashboard host's local time;
- new event from Developer, Workstation, Homelab, Launcher, or Automation;
- a published metric crossing a selected threshold.

Actions:

- create a dashboard notification;
- deliver one locally approved Launcher task that does not require interactive
  confirmation.

Start with a notification rule. Review its run history and cooldown behavior
before considering an unattended local task. Metric rules fire when a condition
changes from false to true, not continuously while it stays true. Missed
schedules advance rather than replaying an unbounded backlog.

Automation cannot add a launcher command or bypass the deployment's two remote
execution switches, the runner's local policy, runner availability, or task
identity. A task marked as requiring confirmation is never automation-eligible.

## Unified Nerd Inbox

Use the top-bar badge or Inbox module to combine bounded signals from GitHub,
companions, Homelab, Launcher, and Automation. Filter by source/state, search,
pin, snooze, archive, or mark a source read.

Those actions organize Kasugai's owner-scoped overlay. They do not acknowledge
a Docker alert at its source, restart an agent, or mark a GitHub notification
read. A connector failure is isolated, so other sources can continue loading.

External links are limited to canonical credential-free GitHub repository
destinations. Local links navigate only to known dashboard sections.

## Knowledge Vault

Create a **Note** or **Snippet**, then provide a title, content, optional
language, up to 12 comma-separated tags, and optional pinned state. Search is a
bounded literal search over your decrypted entries; snippets are copied or
displayed as text and are never executed.

Kasugai does not render Vault content as HTML or Markdown. This prevents a note
from becoming active page code, but you should still avoid storing passwords or
provider secrets in general-purpose notes.

If another browser edits the same item first, your stale update returns a
conflict and the current record is refreshed rather than silently overwritten.

## Network & Security Center

The Security Center summarizes posture from data Kasugai already holds:
agent freshness, resource pressure, container/check health, runner state,
session-cookie/proxy posture, encrypted storage, and execution switches.

It is passive. It does not scan a LAN, probe ports, discover devices, or expose
raw addresses/task arguments. Treat the score as an explainable checklist, not
a vulnerability scan or guarantee. Read each finding and ask the operator to
review configuration-bound items.

## Local AI Toolbox

The Toolbox provides owner-scoped conversations with the operator-configured
private `ollama` compatible endpoint. Start a session with a title and fixed
mode such as general assistance, explanation, review, refactoring, tests,
documentation, regular expressions, or SQL.

Only the text and bounded history in that Toolbox conversation are sent to the
configured endpoint. It cannot inspect a repository, browse, open a URL,
execute a command, query a database, or apply a change. Output is displayed as
inert text. For project-aware review and explicit proposed project updates, use
Ask Kasugai from a project instead.

Hosted personal OpenAI keys do not enable the Local AI Toolbox; it deliberately
requires the deployment's `ollama` provider.

## Personal Hub

Personal Hub provides encrypted owner-scoped items:

- reminders with due time and completion state;
- countdowns with a target time;
- daily, weekday, or weekly habits and bounded check-ins;
- credential-free HTTPS bookmarks.

The focus timer is a browser-side aid with 25-, 5-, and 50-minute presets. It
does not create an external calendar item, notification permission, or durable
automation rule.

Concurrent stale writes return a conflict instead of replacing newer data.
Bookmarks are validated but are not fetched by the server; opening one is an
explicit browser action.

## Appearance and application settings

Settings can manage quick-launch links, a background image, log level, and the
configured transfer/download folder where the deployment permits it. Background
uploads are validated as supported static image formats with bounded size and
dimensions; changing the visual does not grant access to arbitrary server files.

Application settings affect the shared deployment, so only change an option you
understand. Provider secrets and pairing tokens are intentionally not displayed
there.

## Data ownership and recovery expectations

Projects, personal credentials, companion records, AI sessions, inbox overlay,
Vault, Automation, and Personal Hub state are owner-scoped. Encryption at rest
protects selected application fields from casual database inspection, but the
deployment operator controls the process, config key, backups, and storage.

Do not use Kasugai as the only durable record for Team Room chat or active file
offers. Ask the operator about backup, retention, and recovery policy for
project/personal data. Deleting a browser session does not delete server data;
use the feature's delete/revoke controls where available.

For errors, start with [Operations and troubleshooting](TROUBLESHOOTING.md). For
security boundaries and provider data flow, see
[Architecture and security](ARCHITECTURE.md).
