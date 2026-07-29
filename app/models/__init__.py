# All SQLAlchemy model modules must be imported here so that:
# 1. Alembic autogenerate can detect all tables via Base.metadata
# 2. Relationship back-references resolve at startup

from app.models.user import User, OTPCode, PasswordResetToken, RefreshToken  # noqa: F401
from app.models.organization import Organization, OrganizationMember  # noqa: F401
from app.models.event import Event, EventSession, EventCategory, event_category_link  # noqa: F401
from app.models.ticketing import (  # noqa: F401
    TicketType,
    RegistrationFormField,
    Registration,
    RegistrationAnswer,
    Order,
    OrderItem,
    PromoCode,
    Waitlist,
)
from app.models.speaker import Speaker, Sponsor  # noqa: F401
from app.models.campaign import Campaign, CampaignRecipient  # noqa: F401
from app.models.checkin import Checkin  # noqa: F401
from app.models.community import (  # noqa: F401
    AttendeeProfile,
    Connection,
    OrganizerFollower,
    WhatsAppMessage,
)
from app.models.notification import Notification, AuditLog  # noqa: F401
from app.models.payment import PaymentAccount, Payout  # noqa: F401
from app.models.api import ApiKey, WebhookSubscription, WebhookDelivery  # noqa: F401
from app.models.vendor import Vendor, VendorLead  # noqa: F401

__all__ = [
    "User", "OTPCode", "PasswordResetToken", "RefreshToken",
    "Organization", "OrganizationMember",
    "Event", "EventSession", "EventCategory",
    "TicketType", "RegistrationFormField", "Registration", "RegistrationAnswer",
    "Order", "OrderItem", "PromoCode", "Waitlist",
    "Speaker", "Sponsor",
    "Campaign", "CampaignRecipient",
    "Checkin",
    "AttendeeProfile", "Connection", "OrganizerFollower", "WhatsAppMessage",
    "Notification", "AuditLog",
    "PaymentAccount", "Payout",
    "ApiKey", "WebhookSubscription", "WebhookDelivery",
    "Vendor", "VendorLead",
]
