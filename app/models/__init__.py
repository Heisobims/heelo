# All SQLAlchemy model modules must be imported here so that:
# 1. Alembic autogenerate can detect all tables via Base.metadata
# 2. Relationship back-references resolve at startup

from app.models.affiliate import AffiliatePayout, EventAffiliate  # noqa: F401
from app.models.api import ApiKey, WebhookDelivery, WebhookSubscription  # noqa: F401
from app.models.campaign import Campaign, CampaignRecipient  # noqa: F401
from app.models.checkin import Checkin  # noqa: F401
from app.models.community import (  # noqa: F401
    AttendeeProfile,
    Connection,
    EventInterest,
    OrganizerFollower,
    WhatsAppMessage,
)
from app.models.event import (  # noqa: F401
    Event,
    EventCategory,
    EventSession,
    EventSessionBookmark,
    event_category_link,
)
from app.models.feedback import EventFeedback  # noqa: F401
from app.models.notification import AdminBroadcast, AuditLog, Notification  # noqa: F401
from app.models.organization import Organization, OrganizationMember  # noqa: F401
from app.models.payment import PaymentAccount, Payout  # noqa: F401
from app.models.speaker import Speaker, Sponsor  # noqa: F401
from app.models.ticketing import (  # noqa: F401
    Order,
    OrderItem,
    PromoCode,
    Registration,
    RegistrationAnswer,
    RegistrationFormField,
    TicketType,
    Waitlist,
)
from app.models.user import OTPCode, PasswordResetToken, RefreshToken, User  # noqa: F401
from app.models.vendor import (  # noqa: F401
    BoothApplication,
    EventBoothPackage,
    Vendor,
    VendorBooking,
    VendorFeaturedCampaign,
    VendorLead,
    VendorLeadCreditPurchase,
    VendorPayout,
    VendorQuotation,
    VendorQuoteRecipient,
    VendorQuoteRequest,
    VendorReview,
    VendorServiceListing,
    VendorSubscription,
    VendorTransaction,
    VendorVerificationRequest,
)

__all__ = [
    "User",
    "OTPCode",
    "PasswordResetToken",
    "RefreshToken",
    "Organization",
    "OrganizationMember",
    "Event",
    "EventSession",
    "EventCategory",
    "TicketType",
    "RegistrationFormField",
    "Registration",
    "RegistrationAnswer",
    "Order",
    "OrderItem",
    "PromoCode",
    "Waitlist",
    "Speaker",
    "Sponsor",
    "Campaign",
    "CampaignRecipient",
    "Checkin",
    "EventFeedback",
    "AttendeeProfile",
    "Connection",
    "EventInterest",
    "OrganizerFollower",
    "WhatsAppMessage",
    "Notification",
    "AuditLog",
    "AdminBroadcast",
    "PaymentAccount",
    "Payout",
    "ApiKey",
    "WebhookSubscription",
    "WebhookDelivery",
    "Vendor",
    "VendorLead",
    "EventBoothPackage",
    "BoothApplication",
    "VendorServiceListing",
    "VendorQuoteRequest",
    "VendorQuoteRecipient",
    "VendorQuotation",
    "VendorBooking",
    "VendorReview",
    "VendorTransaction",
    "VendorSubscription",
    "VendorFeaturedCampaign",
    "VendorLeadCreditPurchase",
    "VendorPayout",
    "VendorVerificationRequest",
    "EventAffiliate",
    "AffiliatePayout",
    "EventSessionBookmark",
]
