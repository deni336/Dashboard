# Project Routes Documentation

## Summary

`project_bp` serves the collaborative project-management workspace and its session-scoped JSON API. `init_project_routes` initializes the SQLite `ProjectStore` from the application configuration.

## Workspace

- `GET /projects` renders the portfolio and project workspace.
- `GET /api/projects/portfolio` returns portfolio metrics, projects, and global connections.
- `POST /api/projects` creates a project.
- `GET|PATCH|DELETE /api/projects/<id>` reads, updates, or deletes a project according to the caller's access role.

## Sharing

- `POST /api/projects/<id>/shares` creates or rotates a seven-day email invitation. Owners only.
- `PATCH /api/project-shares/<id>` changes viewer/editor access. Owners only.
- `DELETE /api/project-shares/<id>` revokes pending or accepted access. Owners only.
- `GET|POST /projects/invitations/<token>` previews and accepts an invitation for the exact authenticated email address.
- Owner access includes editing, sharing, and deletion. Editor access includes project and child-record edits. Viewer access is read-only.
- Invitation URLs use `[WebServer] publicurl` when configured and otherwise use the current request origin.

## Project Records

- `POST /api/projects/<id>/records` creates a task, milestone, RAID item, or decision.
- `PATCH|DELETE /api/project-records/<id>` updates or deletes a record.
- `POST /api/projects/<id>/meetings` and `PATCH|DELETE /api/project-meetings/<id>` maintain meeting notes.
- `POST /api/projects/<id>/stakeholders` and `PATCH|DELETE /api/project-stakeholders/<id>` maintain the stakeholder register.
- `POST /api/project-connections` and `PATCH|DELETE /api/project-connections/<id>` maintain global or project-scoped links. Connection changes require owner access.

## AI Copilot

- `GET|PUT|DELETE /api/project-ai/settings` reads status, saves, or removes the authenticated user's encrypted personal OpenAI API key. Status responses never contain the key.
- `POST /api/projects/<id>/assistant/preview` sends bounded workspace context to the OpenAI Responses API and returns a signed, non-mutating proposal.
- `POST /api/projects/<id>/assistant/apply` verifies the proposal signature and atomically applies the selected action indexes.
- Preview requires editor access and uses the authenticated actor's personal key when configured. Otherwise, the deployment key is available only to IDs or emails in `KASUGAI_AI_ALLOWED_USERS`.
- Apply requires editor access and an unexpired actor-bound signed proposal; rotating or removing a key does not invalidate an already generated proposal.
- Linked GitHub or IMAP evidence additionally requires project-owner access and an ID or email in `KASUGAI_AI_SOURCE_ALLOWED_USERS`; shared editors and other AI users never exercise deployment-wide source credentials.
- Previews expire after 15 minutes and are rejected if the project or any targeted record changed after generation.
- Preview generation is limited to ten requests per account per ten-minute window in each dashboard process.

## Data Controls

- Every operation derives its owner key from the authenticated Flask session.
- Personal OpenAI keys are encrypted with Fernet, isolated by owner key, accepted only by same-origin credential mutations, and never returned after submission. A corrupt or rejected personal key never falls back to the deployment key.
- Project codes are unique per owner, not globally, and private owner identifiers are never returned in API payloads.
- Accepted shares are joined to the recipient's authenticated owner key; invitation acceptance also requires an exact email match.
- Invitation tokens are random, stored only as SHA-256 hashes, single-use, and expire after seven days.
- Text, enum, date, numeric, email, and URL values are validated before persistence.
- Connection URLs accept only HTTP(S) addresses without embedded credentials.
- AI requests accept at most 256 KiB of JSON, source retrieval and upstream calls share a hard request deadline, only two previews run concurrently, and email attachments are excluded.
- AI proposals use strict action schemas, evidence references, signed confirmation, replay prevention, and an encrypted audit record.
- Project descriptions and long-form project content are encrypted with Fernet before being stored in SQLite.
- Invited and inviter email addresses are encrypted; a key-derived HMAC supports exact email lookup without plaintext storage.
- Collaborators see project-scoped connections but never the owner's portfolio-level connections.
- Foreign-key cascades remove child records when a project is deleted.

## Configuration

`[Database] projectdbpath` selects the project database. Relative paths are stored beside the normal Kasugai configuration, which is persisted by the Docker `dashboard-data` volume. `[WebServer] publicurl` or `KASUGAI_PUBLIC_URL` supplies the externally reachable invitation origin.
