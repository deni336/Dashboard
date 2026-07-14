# Project Routes Documentation

## Summary

`project_bp` serves the project-management workspace and its user-scoped JSON API. `init_project_routes` initializes the SQLite `ProjectStore` from the application configuration.

## Workspace

- `GET /projects` renders the portfolio and project workspace.
- `GET /api/projects/portfolio` returns portfolio metrics, projects, and global connections.
- `POST /api/projects` creates a project.
- `GET|PATCH|DELETE /api/projects/<id>` reads, updates, or deletes an owned project.

## Project Records

- `POST /api/projects/<id>/records` creates a task, milestone, RAID item, or decision.
- `PATCH|DELETE /api/project-records/<id>` updates or deletes a record.
- `POST /api/projects/<id>/meetings` and `PATCH|DELETE /api/project-meetings/<id>` maintain meeting notes.
- `POST /api/projects/<id>/stakeholders` and `PATCH|DELETE /api/project-stakeholders/<id>` maintain the stakeholder register.
- `POST /api/project-connections` and `PATCH|DELETE /api/project-connections/<id>` maintain global or project-scoped links.

## Data Controls

- Every operation derives its owner key from the authenticated Flask session.
- Text, enum, date, numeric, email, and URL values are validated before persistence.
- Connection URLs accept only HTTP(S) addresses without embedded credentials.
- Project descriptions and long-form project content are encrypted with Fernet before being stored in SQLite.
- Foreign-key cascades remove child records when a project is deleted.

## Configuration

`[Database] projectdbpath` selects the project database. Relative paths are stored beside the normal Kasugai configuration, which is persisted by the Docker `dashboard-data` volume.
