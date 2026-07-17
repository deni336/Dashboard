import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from src.config_handler import get_default_config_path
from src.global_logger import GlobalLogger


GITHUB_API_ORIGIN = "https://api.github.com"
MAX_REPOSITORY_ROOTS = 12
MAX_REPOSITORIES = 250
MAX_SCAN_DEPTH = 6
MAX_GIT_OUTPUT = 64 * 1024
GIT_TIMEOUT_SECONDS = 5
GIT_LOG_FORMAT = "%H%x1f%h%x1f%s%x1f%an%x1f%cI"
ALLOWED_GIT_ARGUMENTS = {
    ("status", "--porcelain=v1", "--branch"),
    ("log", "-1", f"--format={GIT_LOG_FORMAT}"),
    ("config", "--get", "remote.origin.url"),
}
SKIPPED_DIRECTORIES = {
    ".cache",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "target",
    "vendor",
    "venv",
}
GITHUB_SLUG = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


def _now():
    return datetime.now(UTC).isoformat()


def _resolve_database_path(config):
    configured = config.get(
        "Database",
        "dashboarddbpath",
        fallback="personal_dashboard.db",
    )
    if os.path.isabs(configured):
        return os.path.abspath(configured)
    config_file = getattr(config, "config_file", None) or get_default_config_path()
    return os.path.abspath(os.path.join(os.path.dirname(config_file), configured))


class PersonalDashboardStore:
    """User-scoped storage shared by the personal dashboard modules."""

    def __init__(self, config):
        self.logger = GlobalLogger.get_logger("PersonalDashboardStore")
        key = config.get("Database", "encryption_key", fallback="")
        if not key:
            key = Fernet.generate_key().decode("ascii")
            config.set("Database", "encryption_key", key)
        self.fernet = Fernet(key.encode("ascii"))
        self.lookup_key = hashlib.sha256(
            b"Kasugai/personal-dashboard/v1\x00" + key.encode("ascii")
        ).digest()
        self.db_path = _resolve_database_path(config)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dashboard_preferences (
                    owner_key TEXT PRIMARY KEY,
                    layout_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dashboard_connectors (
                    owner_key TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    secret TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(owner_key, provider)
                );

                CREATE TABLE IF NOT EXISTS developer_roots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    path_hash TEXT NOT NULL,
                    path TEXT NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_key, path_hash)
                );
                CREATE INDEX IF NOT EXISTS developer_roots_owner_idx
                    ON developer_roots(owner_key, id);

                CREATE TABLE IF NOT EXISTS developer_repository_preferences (
                    owner_key TEXT NOT NULL,
                    repository_key TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
                    alias TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(owner_key, repository_key)
                );

                CREATE TABLE IF NOT EXISTS dashboard_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'info'
                        CHECK (severity IN ('info', 'success', 'warning', 'error')),
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    resource_url TEXT NOT NULL DEFAULT '',
                    dedupe_key TEXT,
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS dashboard_events_owner_idx
                    ON dashboard_events(owner_key, occurred_at DESC, id DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS dashboard_events_dedupe_idx
                    ON dashboard_events(owner_key, dedupe_key)
                    WHERE dedupe_key IS NOT NULL;
                """
            )
        self.logger.info("Connected to personal dashboard database at %s", self.db_path)

    def _encrypt(self, value):
        return self.fernet.encrypt(str(value or "").encode("utf-8")).decode("ascii")

    def _decrypt(self, value):
        try:
            return self.fernet.decrypt(str(value).encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ValueError("Stored dashboard data could not be decrypted") from exc

    def opaque_key(self, value):
        return hmac.new(
            self.lookup_key,
            os.path.normcase(str(value)).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]

    def roots(self, owner_key):
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, path, label, created_at, updated_at
                   FROM developer_roots WHERE owner_key = ? ORDER BY label COLLATE NOCASE, id""",
                (owner_key,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "path": self._decrypt(row["path"]),
                "label": row["label"],
                "source": "user",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def add_root(self, owner_key, path, label):
        timestamp = _now()
        path_hash = self.opaque_key(path)
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """INSERT INTO developer_roots
                       (owner_key, path_hash, path, label, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        owner_key,
                        path_hash,
                        self._encrypt(path),
                        label,
                        timestamp,
                        timestamp,
                    ),
                )
                root_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("That repository root is already configured") from exc
        return next(root for root in self.roots(owner_key) if root["id"] == root_id)

    def remove_root(self, owner_key, root_id):
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM developer_roots WHERE owner_key = ? AND id = ?",
                (owner_key, root_id),
            )
        if cursor.rowcount != 1:
            raise KeyError("Repository root not found")

    def repository_preferences(self, owner_key):
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT repository_key, favorite, alias
                   FROM developer_repository_preferences WHERE owner_key = ?""",
                (owner_key,),
            ).fetchall()
        return {
            row["repository_key"]: {
                "favorite": bool(row["favorite"]),
                "alias": row["alias"],
            }
            for row in rows
        }

    def set_repository_favorite(self, owner_key, repository_key, favorite):
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO developer_repository_preferences
                   (owner_key, repository_key, favorite, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(owner_key, repository_key) DO UPDATE SET
                       favorite = excluded.favorite,
                       updated_at = excluded.updated_at""",
                (owner_key, repository_key, 1 if favorite else 0, timestamp),
            )

    def connector_status(self, owner_key, provider):
        with self._connect() as connection:
            row = connection.execute(
                """SELECT metadata_json, updated_at FROM dashboard_connectors
                   WHERE owner_key = ? AND provider = ?""",
                (owner_key, provider),
            ).fetchone()
        if not row:
            return {"configured": False, "metadata": {}, "updated_at": None}
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, ValueError):
            metadata = {}
        return {
            "configured": True,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "updated_at": row["updated_at"],
        }

    def connector_secret(self, owner_key, provider):
        with self._connect() as connection:
            row = connection.execute(
                """SELECT secret FROM dashboard_connectors
                   WHERE owner_key = ? AND provider = ?""",
                (owner_key, provider),
            ).fetchone()
        return self._decrypt(row["secret"]) if row else ""

    def save_connector(self, owner_key, provider, secret, metadata=None):
        timestamp = _now()
        metadata_json = json.dumps(metadata or {}, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO dashboard_connectors
                   (owner_key, provider, secret, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(owner_key, provider) DO UPDATE SET
                       secret = excluded.secret,
                       metadata_json = excluded.metadata_json,
                       updated_at = excluded.updated_at""",
                (
                    owner_key,
                    provider,
                    self._encrypt(secret),
                    metadata_json,
                    timestamp,
                    timestamp,
                ),
            )

    def delete_connector(self, owner_key, provider):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM dashboard_connectors WHERE owner_key = ? AND provider = ?",
                (owner_key, provider),
            )


def parse_repository_roots(value):
    """Parse a JSON array or platform-separated repository-root environment value."""
    raw = str(value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return []
        values = parsed if isinstance(parsed, list) else []
    else:
        values = raw.split(os.pathsep)
    roots = []
    seen = set()
    for item in values:
        item = str(item).strip()
        if not item:
            continue
        path = os.path.realpath(os.path.abspath(os.path.expanduser(item)))
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        roots.append(path)
    return roots[:MAX_REPOSITORY_ROOTS]


def normalize_repository_root(path):
    candidate = str(path or "").strip()
    if not candidate or len(candidate) > 2048 or "\x00" in candidate:
        raise ValueError("Enter a valid repository root path")
    resolved = os.path.realpath(os.path.abspath(os.path.expanduser(candidate)))
    if not os.path.isdir(resolved):
        raise ValueError("That repository root does not exist or is not visible to Kasugai")
    if os.path.islink(candidate):
        raise ValueError("Repository roots cannot be symbolic links")
    return resolved


def _default_root_label(path):
    name = Path(path).name.strip()
    return name[:80] if name else "Repositories"


def repository_root_allowed(path):
    configured = os.getenv("KASUGAI_REPOSITORY_ALLOWED_ROOTS", "")
    allowed_roots = parse_repository_roots(
        configured or os.getenv("KASUGAI_REPOSITORY_ROOTS", "")
    )
    if not allowed_roots:
        return False
    candidate = os.path.normcase(os.path.realpath(path))
    for allowed in allowed_roots:
        try:
            normalized_allowed = os.path.normcase(os.path.realpath(allowed))
            if os.path.commonpath((candidate, normalized_allowed)) == normalized_allowed:
                return True
        except ValueError:
            continue
    return False


def _path_is_within(path, root):
    """Return whether a resolved path stays at or below a resolved root."""
    candidate = os.path.normcase(os.path.realpath(path))
    boundary = os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath((candidate, boundary)) == boundary
    except ValueError:
        return False


def _repository_marker_is_safe(repository_path, scan_root):
    """Reject symlinked or out-of-root Git metadata discovered during a scan."""
    if not _path_is_within(repository_path, scan_root):
        return False
    marker = os.path.join(repository_path, ".git")
    if os.path.islink(marker):
        return False
    if os.path.isdir(marker):
        return _path_is_within(marker, scan_root)
    if not os.path.isfile(marker):
        return False
    try:
        if os.path.getsize(marker) > 4096:
            return False
        with open(marker, encoding="utf-8", errors="strict") as marker_file:
            contents = marker_file.read(4097).strip()
    except (OSError, UnicodeError):
        return False
    match = re.fullmatch(r"gitdir:\s*(.+)", contents, flags=re.IGNORECASE)
    if not match:
        return False
    git_directory = match.group(1).strip()
    if not git_directory or "\x00" in git_directory:
        return False
    if not os.path.isabs(git_directory):
        git_directory = os.path.join(repository_path, git_directory)
    return os.path.isdir(git_directory) and _path_is_within(git_directory, scan_root)


def _command_creation_flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _run_git(repository_path, *arguments):
    if tuple(arguments) not in ALLOWED_GIT_ARGUMENTS:
        raise ValueError("Unsupported Git inspection command")
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.upper().startswith("GIT_"):
            environment.pop(name, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "PAGER": "cat",
        }
    )
    completed = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "--no-pager",
            "-c",
            f"safe.directory={repository_path}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "diff.external=",
            "-c",
            "credential.helper=",
            "-C",
            repository_path,
            *arguments,
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
        env=environment,
        creationflags=_command_creation_flags(),
        check=False,
    )
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if len(output) > MAX_GIT_OUTPUT:
        output = output[:MAX_GIT_OUTPUT]
    if completed.returncode != 0:
        raise RuntimeError(error[:500] or "Git command failed")
    return output


def _safe_remote(remote):
    value = str(remote or "").strip()
    if not value:
        return {"remote_url": "", "web_url": "", "github_slug": ""}
    web_url = ""
    github_slug = ""
    if value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlsplit(value)
        hostname = (parsed.hostname or "").lower()
        clean_path = parsed.path
        if parsed.scheme == "https" and hostname == "github.com" and not parsed.port:
            github_slug = clean_path.strip("/").removesuffix(".git")
            value = f"https://github.com/{github_slug}.git"
            web_url = f"https://github.com/{github_slug}"
        else:
            # Do not disclose private forge hosts or repository paths. Additional
            # providers can be exposed later through a deployment allowlist.
            value = ""
    else:
        match = re.fullmatch(r"(?:ssh://)?git@github\.com[:/]([^/]+/[^/]+?)(?:\.git)?", value)
        if match:
            github_slug = match.group(1).removesuffix(".git")
            web_url = f"https://github.com/{github_slug}"
            value = f"git@github.com:{github_slug}.git"
        else:
            # Local filesystem paths and unrecognized SSH remotes are not useful
            # to the browser and can disclose host details.
            value = ""
    if not GITHUB_SLUG.fullmatch(github_slug):
        return {"remote_url": "", "web_url": "", "github_slug": ""}
    return {"remote_url": value, "web_url": web_url, "github_slug": github_slug}


def _parse_status(output):
    lines = output.splitlines()
    branch = ""
    upstream = ""
    ahead = 0
    behind = 0
    if lines and lines[0].startswith("## "):
        header = lines.pop(0)[3:]
        tracking = re.match(
            r"(?P<branch>.+?)(?:\.\.\.(?P<upstream>[^ ]+))?(?: \[(?P<counts>.+)\])?$",
            header,
        )
        if tracking:
            branch = tracking.group("branch")
            upstream = tracking.group("upstream") or ""
            counts = tracking.group("counts") or ""
            ahead_match = re.search(r"ahead (\d+)", counts)
            behind_match = re.search(r"behind (\d+)", counts)
            ahead = int(ahead_match.group(1)) if ahead_match else 0
            behind = int(behind_match.group(1)) if behind_match else 0
    staged = modified = untracked = conflicted = 0
    conflict_codes = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
    for line in lines:
        if len(line) < 2:
            continue
        code = line[:2]
        if code == "??":
            untracked += 1
            continue
        if code in conflict_codes:
            conflicted += 1
        if code[0] not in {" ", "?"}:
            staged += 1
        if code[1] not in {" ", "?"}:
            modified += 1
    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "modified": modified,
        "untracked": untracked,
        "conflicted": conflicted,
        "dirty": bool(staged or modified or untracked or conflicted),
    }


class DeveloperCockpit:
    def __init__(self, store):
        self.store = store
        self.logger = GlobalLogger.get_logger("DeveloperCockpit")

    @staticmethod
    def git_available():
        try:
            completed = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                timeout=2,
                creationflags=_command_creation_flags(),
                check=False,
            )
            return completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def roots(self, owner_key):
        roots = self.store.roots(owner_key)
        known = {os.path.normcase(root["path"]) for root in roots}
        for path in parse_repository_roots(os.getenv("KASUGAI_REPOSITORY_ROOTS")):
            if os.path.normcase(path) in known:
                continue
            roots.append(
                {
                    "id": f"environment:{self.store.opaque_key(path)}",
                    "path": path,
                    "label": _default_root_label(path),
                    "source": "environment",
                    "created_at": None,
                    "updated_at": None,
                }
            )
        return roots[:MAX_REPOSITORY_ROOTS]

    @staticmethod
    def public_root(root, *, available=None, repository_count=None):
        """Create the path-redacted representation used by HTTP responses."""
        result = {
            "id": root["id"],
            "label": root["label"],
            "source": root["source"],
            "created_at": root.get("created_at"),
            "updated_at": root.get("updated_at"),
        }
        if available is not None:
            result["available"] = bool(available)
        if repository_count is not None:
            result["repository_count"] = int(repository_count)
        return result

    def public_roots(self, owner_key):
        return [
            self.public_root(root, available=os.path.isdir(root["path"]))
            for root in self.roots(owner_key)
        ]

    def add_root(self, owner_key, path, label=""):
        if len(self.store.roots(owner_key)) >= MAX_REPOSITORY_ROOTS:
            raise ValueError(f"A maximum of {MAX_REPOSITORY_ROOTS} repository roots is supported")
        resolved = normalize_repository_root(path)
        if not repository_root_allowed(resolved):
            raise ValueError(
                "That path is outside the repository roots allowed by this Kasugai deployment"
            )
        clean_label = " ".join(str(label or "").split())[:80] or _default_root_label(resolved)
        return self.store.add_root(owner_key, resolved, clean_label)

    def remove_root(self, owner_key, root_id):
        self.store.remove_root(owner_key, root_id)

    @staticmethod
    def _discover(root_path, max_depth):
        repositories = []
        scan_root = os.path.realpath(root_path)
        stack = [(scan_root, 0)]
        seen = set()
        while stack and len(repositories) < MAX_REPOSITORIES:
            current, depth = stack.pop()
            normalized = os.path.normcase(os.path.realpath(current))
            if normalized in seen or not _path_is_within(normalized, scan_root):
                continue
            seen.add(normalized)
            try:
                if _repository_marker_is_safe(current, scan_root):
                    repositories.append(os.path.realpath(current))
                    continue
                if depth >= max_depth:
                    continue
                with os.scandir(current) as entries:
                    children = [
                        entry.path
                        for entry in entries
                        if entry.is_dir(follow_symlinks=False)
                        and entry.name not in SKIPPED_DIRECTORIES
                        and not entry.name.startswith(".")
                    ]
                stack.extend((child, depth + 1) for child in reversed(children))
            except (OSError, PermissionError):
                continue
        return repositories

    def _inspect_repository(self, path, display_path, preferences):
        repository_key = self.store.opaque_key(path)
        preference = preferences.get(repository_key, {})
        result = {
            "id": repository_key,
            "name": preference.get("alias") or Path(path).name,
            "display_path": display_path,
            "favorite": bool(preference.get("favorite")),
            "available": True,
            "error": "",
        }
        try:
            result.update(_parse_status(_run_git(path, "status", "--porcelain=v1", "--branch")))
            try:
                log = _run_git(
                    path,
                    "log",
                    "-1",
                    f"--format={GIT_LOG_FORMAT}",
                )
            except RuntimeError:
                log = ""
            if log:
                parts = log.split("\x1f", 4)
                if len(parts) == 5:
                    result["last_commit"] = {
                        "hash": parts[0],
                        "short_hash": parts[1],
                        "subject": parts[2],
                        "author": parts[3],
                        "committed_at": parts[4],
                    }
            try:
                result.update(_safe_remote(_run_git(path, "config", "--get", "remote.origin.url")))
            except RuntimeError:
                result.update(_safe_remote(""))
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.logger.warning("Git inspection failed for repository %s: %s", result["id"], exc)
            result.update(
                {
                    "available": False,
                    "error": "Git could not inspect this repository",
                    "dirty": False,
                    "branch": "",
                    "upstream": "",
                    "ahead": 0,
                    "behind": 0,
                    "staged": 0,
                    "modified": 0,
                    "untracked": 0,
                    "conflicted": 0,
                    "remote_url": "",
                    "web_url": "",
                    "github_slug": "",
                }
            )
        return result

    def overview(self, owner_key, max_depth=None):
        depth = max(1, min(int(max_depth or 4), MAX_SCAN_DEPTH))
        roots = self.roots(owner_key)
        preferences = self.store.repository_preferences(owner_key)
        discovered = []
        root_results = []
        for root in roots:
            exists = os.path.isdir(root["path"])
            repository_paths = self._discover(root["path"], depth) if exists else []
            for repository_path in repository_paths:
                relative = os.path.relpath(repository_path, root["path"])
                display_path = root["label"] if relative == "." else f"{root['label']}/{relative}"
                discovered.append((repository_path, display_path.replace("\\", "/")))
            root_results.append(
                self.public_root(
                    root,
                    available=exists,
                    repository_count=len(repository_paths),
                )
            )

        unique_paths = []
        seen = set()
        for path, display_path in discovered:
            key = os.path.normcase(os.path.realpath(path))
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append((path, display_path))
            if len(unique_paths) >= MAX_REPOSITORIES:
                break

        repositories = []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(unique_paths)))) as executor:
            futures = {
                executor.submit(self._inspect_repository, path, display_path, preferences): path
                for path, display_path in unique_paths
            }
            for future in as_completed(futures):
                repositories.append(future.result())
        repositories.sort(
            key=lambda repository: (
                not repository["favorite"],
                repository["name"].casefold(),
                repository["display_path"].casefold(),
            )
        )
        return {
            "generated_at": _now(),
            "git_available": self.git_available(),
            "roots": root_results,
            "repositories": repositories,
            "summary": {
                "total": len(repositories),
                "favorites": sum(1 for item in repositories if item["favorite"]),
                "dirty": sum(1 for item in repositories if item.get("dirty")),
                "ahead": sum(1 for item in repositories if item.get("ahead", 0) > 0),
                "behind": sum(1 for item in repositories if item.get("behind", 0) > 0),
                "unavailable": sum(1 for item in repositories if not item.get("available")),
            },
            "github": self.store.connector_status(owner_key, "github"),
        }

    def set_favorite(self, owner_key, repository_key, favorite):
        if not re.fullmatch(r"[0-9a-f]{32}", str(repository_key or "")):
            raise ValueError("Invalid repository identifier")
        self.store.set_repository_favorite(owner_key, repository_key, bool(favorite))

    @staticmethod
    def _github_request(path, token):
        if not path.startswith("/") or "\r" in path or "\n" in path:
            raise ValueError("Invalid GitHub API path")
        request = urllib.request.Request(
            f"{GITHUB_API_ORIGIN}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "Kasugai-Dashboard",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        try:
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(request, timeout=8) as response:
                return json.loads(response.read(512 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise PermissionError("GitHub rejected this token or its permissions") from exc
            raise RuntimeError(f"GitHub returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("GitHub could not be reached") from exc

    def configure_github(self, owner_key, token):
        clean_token = str(token or "").strip()
        if not 20 <= len(clean_token) <= 512 or any(character.isspace() for character in clean_token):
            raise ValueError("Enter a valid GitHub personal access token")
        user = self._github_request("/user", clean_token)
        login = str(user.get("login") or "").strip()
        if not login:
            raise ValueError("GitHub did not return an account for this token")
        metadata = {
            # Immutable account identity keeps locally overlaid inbox state
            # separate if a connector is later replaced by another account.
            "account_id": str(user.get("id") or "")[:32],
            "login": login,
            "avatar_url": str(user.get("avatar_url") or ""),
            "html_url": str(user.get("html_url") or ""),
        }
        self.store.save_connector(owner_key, "github", clean_token, metadata)
        return {"configured": True, "metadata": metadata, "updated_at": _now()}

    def github_notifications(self, owner_key):
        token = self.store.connector_secret(owner_key, "github")
        if not token:
            return {"configured": False, "notifications": [], "count": 0}
        payload = self._github_request(
            "/notifications?all=false&participating=false&per_page=30",
            token,
        )
        notifications = []
        for item in payload if isinstance(payload, list) else []:
            repository = item.get("repository") or {}
            subject = item.get("subject") or {}
            notifications.append(
                {
                    "id": str(item.get("id") or ""),
                    "reason": str(item.get("reason") or ""),
                    "unread": bool(item.get("unread", True)),
                    "updated_at": str(item.get("updated_at") or ""),
                    "repository": str(repository.get("full_name") or ""),
                    "repository_url": str(repository.get("html_url") or ""),
                    "title": str(subject.get("title") or ""),
                    "type": str(subject.get("type") or ""),
                }
            )
        return {
            "configured": True,
            "notifications": notifications,
            "count": len(notifications),
            "account": self.store.connector_status(owner_key, "github")["metadata"],
        }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None
