"""Metadata aggregator.

Import this module (never individual model modules) whenever a *complete*
``Base.metadata`` is required: Alembic autogenerate, ``create_all`` in tests, and
the application bootstrap.
"""

from __future__ import annotations

from app.db.base_class import Base, BaseModel, TimestampMixin, UUIDMixin, utcnow
from app.db.models.agent import AgentRun, AgentStep, AgentToolCall
from app.db.models.audit import AuditLog
from app.db.models.auth import (
    CustomRole,
    Permission,
    RefreshToken,
    Role,
    User,
    role_permissions,
    user_roles,
)
from app.db.models.automation import AutomationRun, DomainEvent, ProcessedEvent
from app.db.models.campaign import Campaign, CampaignAction, CampaignAudience
from app.db.models.commerce import Customer, Product, Transaction, TransactionItem
from app.db.models.competitor import Competitor, CompetitorReview
from app.db.models.experiment import Experiment, ExperimentResult, ExperimentVariant
from app.db.models.governance import AgentMessage, ApprovalRequest, FinancialExecution
from app.db.models.growth import GrowthMetric, GrowthOpportunity
from app.db.models.inventory import InventoryBatch, InventoryItem, InventoryMovement
from app.db.models.memory import AgentMemory
from app.db.models.merchant import Merchant, MerchantMembership
from app.db.models.paypal import (
    PayPalInvoiceRecord,
    PayPalSubscriptionRecord,
    PayPalSyncCheckpoint,
    PayPalTransactionRecord,
    PayPalWebhookEvent,
)
from app.db.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    Vendor,
    VendorProduct,
)
from app.db.models.review import Review
from app.db.models.signal import ExternalSignal
from app.db.models.supply import (
    GoodsReceipt,
    InvoiceMatch,
    NegotiationOffer,
    NegotiationSession,
    ProcurementReconciliation,
    ProcurementRequest,
    SupplierAgent,
    SupplierInvoice,
)

__all__ = [
    "AgentMemory",
    "AgentMessage",
    "AgentRun",
    "AgentStep",
    "AgentToolCall",
    "ApprovalRequest",
    "AuditLog",
    "AutomationRun",
    "Base",
    "BaseModel",
    "Campaign",
    "CampaignAction",
    "CampaignAudience",
    "Competitor",
    "CompetitorReview",
    "CustomRole",
    "Customer",
    "DomainEvent",
    "Experiment",
    "ExperimentResult",
    "ExperimentVariant",
    "ExternalSignal",
    "FinancialExecution",
    "GoodsReceipt",
    "GrowthMetric",
    "GrowthOpportunity",
    "InventoryBatch",
    "InventoryItem",
    "InventoryMovement",
    "InvoiceMatch",
    "Merchant",
    "MerchantMembership",
    "NegotiationOffer",
    "NegotiationSession",
    "PayPalInvoiceRecord",
    "PayPalSubscriptionRecord",
    "PayPalSyncCheckpoint",
    "PayPalTransactionRecord",
    "PayPalWebhookEvent",
    "Permission",
    "ProcessedEvent",
    "ProcurementReconciliation",
    "ProcurementRequest",
    "Product",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "RefreshToken",
    "Review",
    "Role",
    "SupplierAgent",
    "SupplierInvoice",
    "TimestampMixin",
    "Transaction",
    "TransactionItem",
    "UUIDMixin",
    "User",
    "Vendor",
    "VendorProduct",
    "role_permissions",
    "user_roles",
    "utcnow",
]
