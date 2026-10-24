from enum import StrEnum


class Role(StrEnum):
    """Workspace roles.

    admin:  everything an agent can do, plus manage members, categories and configuration.
    agent:  create, edit, comment on and transition issues.
    viewer: read-only.
    """

    ADMIN = "admin"
    AGENT = "agent"
    VIEWER = "viewer"
