"""Kasugai's outbound-only Docker and homelab agent."""

from __future__ import annotations

AGENT_VERSION = "0.1.0"
SNAPSHOT_SCHEMA_VERSION = 1
ACTION_SCHEMA_VERSION = 1

__all__ = ["ACTION_SCHEMA_VERSION", "AGENT_VERSION", "SNAPSHOT_SCHEMA_VERSION"]
