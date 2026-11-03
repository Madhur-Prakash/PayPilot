"""RBAC catalogue: the canonical permission set and the role -> permission map.

This module is pure data + helpers. It is imported by the seeder (to populate the
`permissions` / `roles` / `role_permissions` tables), by the auth dependencies
(to build the effective permission set for a request) and by the tests.

Route handlers never compare role strings; they depend on
``require_permission("campaign:execute")`` instead.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    STAFF = "STAFF"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    # analytics / read surfaces
    DASHBOARD_READ = "dashboard:read"
    GROWTH_READ = "growth:read"
    GROWTH_RECOMMEND = "growth:recommend"
    CUSTOMERS_READ = "customers:read"
    PRODUCTS_READ = "products:read"
    REVIEWS_READ = "reviews:read"
    COMPETITORS_READ = "competitors:read"
    SIGNALS_READ = "signals:read"

    # campaigns
    CAMPAIGN_READ = "campaign:read"
    CAMPAIGN_CREATE = "campaign:create"
    CAMPAIGN_APPROVE = "campaign:approve"
    CAMPAIGN_EXECUTE = "campaign:execute"

    # experiments
    EXPERIMENT_READ = "experiment:read"
    EXPERIMENT_CREATE = "experiment:create"
    EXPERIMENT_APPROVE = "experiment:approve"
    EXPERIMENT_MEASURE = "experiment:measure"

    # inventory
    INVENTORY_READ = "inventory:read"
    INVENTORY_WRITE = "inventory:write"
    #: Seeing what stock is *worth* is a separate decision from seeing counts.
    INVENTORY_VALUE_READ = "inventory:value_read"
    INVENTORY_CONFIGURE = "inventory:configure"
    INVENTORY_LEDGER_READ = "inventory:ledger_read"
    INVENTORY_REPORTS_EXPORT = "inventory:reports_export"

    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_ADMIN = "memory:admin"

    # procurement
    VENDOR_READ = "vendor:read"
    VENDOR_MANAGE = "vendor:manage"
    PURCHASE_ORDER_READ = "purchase_order:read"
    PURCHASE_ORDER_CREATE = "purchase_order:create"
    PURCHASE_ORDER_APPROVE = "purchase_order:approve"
    PURCHASE_ORDER_RECEIVE = "purchase_order:receive"

    # automation
    AUTOMATION_VIEW = "automation:view"
    AUTOMATION_MANAGE = "automation:manage"

    # agents
    AGENTS_VIEW = "agents:view"
    AGENTS_RUN = "agents:run"

    # admin
    SETTINGS_MANAGE = "settings:manage"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"


PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.DASHBOARD_READ: "View the growth command center and KPIs",
    Permission.GROWTH_READ: "View growth metrics, the growth graph and opportunities",
    Permission.GROWTH_RECOMMEND: "Ask the Growth Scientist to investigate and recommend",
    Permission.CUSTOMERS_READ: "View customers, cohorts and segments",
    Permission.PRODUCTS_READ: "View product performance",
    Permission.REVIEWS_READ: "View review intelligence",
    Permission.COMPETITORS_READ: "View competitor intelligence",
    Permission.SIGNALS_READ: "View contextual external market signals",
    Permission.CAMPAIGN_READ: "View campaigns",
    Permission.CAMPAIGN_CREATE: "Create campaigns and audiences",
    Permission.CAMPAIGN_APPROVE: "Approve a campaign for execution",
    Permission.CAMPAIGN_EXECUTE: "Execute an approved campaign",
    Permission.EXPERIMENT_READ: "View experiments and results",
    Permission.EXPERIMENT_CREATE: "Create experiments and variants",
    Permission.EXPERIMENT_APPROVE: "Approve and launch an experiment",
    Permission.EXPERIMENT_MEASURE: "Run measurement and record the learning outcome",
    Permission.INVENTORY_READ: "View inventory intelligence",
    Permission.INVENTORY_WRITE: "Record inventory actions such as a reorder decision",
    Permission.INVENTORY_VALUE_READ: "See stock valuation and cost, not just counts",
    Permission.INVENTORY_CONFIGURE: "Set reorder points, strategies and automatic ordering",
    Permission.INVENTORY_LEDGER_READ: "Read the immutable stock movement ledger",
    Permission.INVENTORY_REPORTS_EXPORT: "Export inventory books and reports to Excel",
    Permission.MEMORY_READ: "Search what the agents have learned about this merchant",
    Permission.MEMORY_WRITE: "Teach the agents something they should remember",
    Permission.MEMORY_ADMIN: "Erase this merchant's agent memory",
    Permission.VENDOR_READ: "View suppliers and their terms",
    Permission.VENDOR_MANAGE: "Add and edit suppliers, prices and lead times",
    Permission.PURCHASE_ORDER_READ: "View purchase orders",
    Permission.PURCHASE_ORDER_CREATE: "Raise a purchase order",
    Permission.PURCHASE_ORDER_APPROVE: "Approve or reject a purchase order",
    Permission.PURCHASE_ORDER_RECEIVE: "Record goods received against an order",
    Permission.AUTOMATION_VIEW: "View automation runs and their traces",
    Permission.AUTOMATION_MANAGE: "Retry, pause or resume inventory automation",
    Permission.AGENTS_VIEW: "View agent runs, steps and traces",
    Permission.AGENTS_RUN: "Start an agent run",
    Permission.SETTINGS_MANAGE: "Manage merchant settings",
    Permission.USERS_MANAGE: "Invite users and change roles",
    Permission.AUDIT_READ: "Read the audit log",
}

_READ_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.DASHBOARD_READ,
        Permission.GROWTH_READ,
        Permission.CUSTOMERS_READ,
        Permission.PRODUCTS_READ,
        Permission.REVIEWS_READ,
        Permission.COMPETITORS_READ,
        Permission.SIGNALS_READ,
        Permission.CAMPAIGN_READ,
        Permission.EXPERIMENT_READ,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_LEDGER_READ,
        Permission.VENDOR_READ,
        Permission.PURCHASE_ORDER_READ,
        Permission.AUTOMATION_VIEW,
        Permission.AGENTS_VIEW,
        Permission.MEMORY_READ,
    }
)

_ANALYST: frozenset[Permission] = _READ_ONLY | {
    Permission.GROWTH_RECOMMEND,
    Permission.AGENTS_RUN,
    Permission.CAMPAIGN_CREATE,
    Permission.EXPERIMENT_CREATE,
    Permission.EXPERIMENT_MEASURE,
    Permission.INVENTORY_VALUE_READ,
    Permission.INVENTORY_REPORTS_EXPORT,
    Permission.MEMORY_WRITE,
}

_STAFF: frozenset[Permission] = _READ_ONLY | {
    Permission.INVENTORY_WRITE,
    Permission.PURCHASE_ORDER_RECEIVE,
    Permission.AGENTS_RUN,
}

_ADMIN: frozenset[Permission] = _ANALYST | {
    Permission.CAMPAIGN_APPROVE,
    Permission.CAMPAIGN_EXECUTE,
    Permission.EXPERIMENT_APPROVE,
    Permission.INVENTORY_WRITE,
    Permission.INVENTORY_CONFIGURE,
    Permission.VENDOR_MANAGE,
    Permission.PURCHASE_ORDER_CREATE,
    Permission.PURCHASE_ORDER_APPROVE,
    Permission.PURCHASE_ORDER_RECEIVE,
    Permission.AUTOMATION_MANAGE,
    Permission.SETTINGS_MANAGE,
    Permission.AUDIT_READ,
    Permission.MEMORY_ADMIN,
}

_OWNER: frozenset[Permission] = _ADMIN | {Permission.USERS_MANAGE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _OWNER,
    Role.ADMIN: _ADMIN,
    Role.ANALYST: _ANALYST,
    Role.STAFF: _STAFF,
    Role.VIEWER: _READ_ONLY,
}

ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.OWNER: "Full control of the merchant account, including users and billing decisions",
    Role.ADMIN: "Operate growth: approve and execute campaigns and experiments",
    Role.ANALYST: "Investigate and propose. Can create but not approve or execute",
    Role.STAFF: "Day-to-day operations. Read analytics and record inventory actions",
    Role.VIEWER: "Read-only access to analytics and agent activity",
}

#: Permissions that gate a financially consequential action. Anything listed here
#: additionally requires a recorded human approval (see services/campaigns, experiments).
APPROVAL_GATED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.CAMPAIGN_EXECUTE,
        Permission.EXPERIMENT_APPROVE,
        Permission.CAMPAIGN_APPROVE,
    }
)

ALL_PERMISSIONS: tuple[Permission, ...] = tuple(Permission)
ALL_ROLES: tuple[Role, ...] = tuple(Role)


def permissions_for_role(role: Role | str) -> frozenset[Permission]:
    try:
        key = Role(role)
    except ValueError:
        return frozenset()
    return ROLE_PERMISSIONS.get(key, frozenset())


def permissions_for_roles(
    roles: list[Role | str] | tuple[Role | str, ...],
) -> frozenset[Permission]:
    result: set[Permission] = set()
    for role in roles:
        result |= permissions_for_role(role)
    return frozenset(result)


def permission_resource(permission: Permission | str) -> str:
    """`campaign:execute` -> `campaign`."""
    return str(permission).split(":", 1)[0]
