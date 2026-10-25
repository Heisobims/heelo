"""
Heelo AI Support & Knowledge Base Assistant Service.

Provides intelligent, context-aware responses to user and visitor queries
about the entire Heelo platform, including:
- Event creation, lifecycle, scheduling, and timezone support
- Multi-currency ticketing, payment fee models, promo codes, and waitlists
- Payment gateways (Paystack, Flutterwave, Stripe) and automated payouts
- Check-in app, Box Office QR scanning, offline sync, and Apple Wallet passes
- Vendor Marketplace (finding, hiring, quoting, milestone escrow payments)
- Marketing tools (Meta, Google, TikTok conversion pixels, abandoned checkout recovery, share cards)
- Corporate compliance (VAT/Tax invoices, PDF receipts via ReportLab)
- Subscription plans (Free, Growth, Pro, Enterprise) and features
- Live database grounding for active events and vendor categories
"""

from __future__ import annotations

import re
from datetime import datetime, UTC
from typing import Any
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = structlog.get_logger()

# ── Knowledge Base Corpus ─────────────────────────────────────────────────────

SYSTEM_KNOWLEDGE_PROMPT = """You are Heelo AI, the intelligent, friendly, and expert support assistant for Heelo.
Heelo is the modern all-in-one event ticketing, event intelligence, and vendor marketplace platform built for organizers and attendees worldwide, with deep multi-currency support (NGN, USD, GBP, EUR, KES, GHS, ZAR).

Your role is to answer questions from event organizers, ticket buyers, and vendors with precision, helpfulness, and clear guidance, similar to modern SaaS support assistants like Hostinger AI or Intercom.

Key Knowledge Points about Heelo:
1. Event Management:
   - Organizers can create, edit, schedule, and publish events at /org/[slug]/events/create.
   - Supports formats: In-person, Virtual (with live stream URLs), and Hybrid.
   - Features customizable registration forms, multi-speaker rosters, session agendas with tracks/stages, and sponsor tiers.
   - Private events can be password-protected or restricted to verified invite links.

2. Ticketing & Multi-Currency Economics:
   - Free Events: 100% free with unlimited tickets and zero platform fees, forever.
   - Paid Tickets: Tiered pricing (Free, General, VIP, Early Bird, Group).
   - Multi-Currency: Organizers can price tickets in NGN, USD, GBP, EUR, KES, GHS, ZAR.
   - Fee Model: By default, platform fees (3.5% + processing) are passed to the ticket buyer (fees_passed_to_buyer = true), so the organizer retains 100% of their face-value ticket revenue. Organizers can also choose to absorb fees.
   - Promo Codes: Discount codes (fixed or percentage), usage limits, and expiration dates.
   - Referral Discounts: Attendees can share unique "Refer a Friend" links for automatic discounts.
   - Waitlist: Built-in waitlist that automatically reserves spots and notifies next in line when tickets become available.

3. Payment Gateways & Automated Payouts:
   - Processors: Paystack, Flutterwave, Stripe Connect, and Stripe Direct.
   - Instant Subaccount Splits: On Paystack and Flutterwave, ticket revenue can split automatically at charge time directly into the organizer's bank account.
   - Payout System: Heelo processes automatic batch payouts with zero platform withholding. Organizers configure bank accounts at /org/[slug]/settings/payments.

4. Check-in, Box Office & Digital Wallet Passes:
   - Box Office: Live check-in scanner at /check-in with 5-second automatic background polling.
   - QR Codes: Signed cryptographic QR codes on every confirmed ticket.
   - Offline Mode: Check-in works offline via Service Worker caching.
   - Digital Passes: Attendees can download official Apple Wallet digital passes (.pkpass) directly from order confirmation.
   - Thermal Badges: Organizers can generate and print professional attendee name badges (/badges.pdf).

5. Vendor Marketplace (/vendors):
   - Organizers can discover and hire verified event vendors across 8 categories: Venues, Catering & Drinks, Photography & Video, Sound & DJ, Decor & Styling, Security & Bouncers, Event Hosts/MCs, Ushers & Protocol.
   - Request for Quote (RFQ) system with chat negotiation.
   - Escrow Payments: Funds are safely held in escrow and released upon milestone completion and fulfillment.
   - Booth Applications: Vendors can apply for exhibition booths on events (/events/[slug]/apply).

6. Marketing, Social Virality & Tracking:
   - Conversion Tracking Pixels: Organizers can configure Meta (Facebook) Pixel ID, Google Tag (GA4/GTM) ID, and TikTok Pixel ID in event settings to track PageView, ViewContent, and Purchase events.
   - Abandoned Checkout Recovery: Celery cron runs every 15 minutes to identify unpaid checkouts and send branded 1-click recovery emails.
   - Viral Share Cards: Attendees get vertical 1080x1920 Instagram Story share cards (/api/v1/events/[slug]/share-card/[id]) to post on social media.

7. Corporate Invoicing & VAT Compliance:
   - Organizers can configure VAT/Tax rate % and registered Tax ID.
   - Corporate checkout allows buyers to input Company Name, Tax ID, and Billing Address.
   - Generates official downloadable PDF tax invoices at /orders/[order_id]/invoice.pdf.

8. Subscription Plans & Pricing (/pricing):
   - Free ($0/month forever): Unlimited events, paid tickets, 1 seat, basic analytics.
   - Growth ($19/month or NGN 7,500/month): Custom branding, 3 seats, recurring events, CRM contact import, custom form fields, speaker agendas, 1,000 WhatsApp messages/month.
   - Pro ($49/month or NGN 25,000/month): Sponsor management, live polls & Q&A, advanced analytics, custom domain (e.g. events.yourbrand.com), 10 seats, 5,000 WhatsApp messages/month.
   - Enterprise: Dedicated manager, full white-label, SSO, unlimited custom domains & API keys.

9. Support & Contact:
   - Direct support email: hello@heelo.io
   - Community & Help: In-app support and knowledge base.

Guidelines for Responses:
- Be warm, encouraging, concise, and structured.
- Use markdown bolding and bullet points for readability.
- Provide direct URLs (like /pricing, /events, /vendors) where relevant.
- If live event listings are provided below, cite them accurately when users ask for event recommendations.
"""


# ── Dynamic Database Grounding ────────────────────────────────────────────────

async def get_live_database_context(db: AsyncSession, query: str) -> str:
    """Fetch live data from the database matching the user's intent."""
    q_lower = query.lower()
    snippets = []

    # Check for event discovery queries
    event_keywords = ["event", "concert", "conference", "party", "festival", "show", "tickets", "happening", "upcoming", "browse"]
    if any(k in q_lower for k in event_keywords):
        from app.models.event import Event
        now = datetime.now(UTC)
        stmt = (
            select(Event)
            .where(Event.status.in_(["published", "live"]), Event.start_datetime >= now)
            .order_by(Event.start_datetime.asc())
            .limit(5)
        )
        events = (await db.scalars(stmt)).all()
        if events:
            lines = ["Live Upcoming Events on Heelo:"]
            for ev in events:
                date_str = ev.start_datetime.strftime("%b %d, %Y") if ev.start_datetime else "Upcoming"
                loc = ev.venue_city or ev.venue_name or ("Online" if ev.format == "virtual" else "TBA")
                lines.append(f"- **{ev.title}** ({loc}, {date_str}) -> Link: /e/{ev.slug}")
            snippets.append("\n".join(lines))

    # Check for vendor queries
    vendor_keywords = ["vendor", "caterer", "catering", "photographer", "dj", "security", "venue", "sound", "lighting", "hire"]
    if any(k in q_lower for k in vendor_keywords):
        snippets.append(
            "Heelo Vendor Marketplace Categories: Venues, Catering & Drinks, Photography & Video, "
            "Sound, Lighting & DJ, Decor & Styling, Security & Bouncers, Event Hosts/MCs, Ushers & Protocol. "
            "Organizers can explore vendors at /vendors or request custom quotes with escrow protection."
        )

    return "\n\n".join(snippets)


# ── Rule-Based Intelligent Fallback Engine ─────────────────────────────────────

def get_rule_based_response(query: str, live_context: str = "") -> dict[str, Any]:
    """
    Intelligent fallback response engine that matches keywords and intents
    when ANTHROPIC_API_KEY is not configured or during offline operations.
    """
    q = query.lower().strip()

    # 1. Greetings & Identity
    if re.search(r"\b(hi|hello|hey|who are you|what is heelo|good morning|good evening)\b", q):
        reply = (
            "**Hello! I'm Heelo AI**, your platform assistant.\n\n"
            "Heelo is the modern all-in-one event ticketing, event intelligence, and vendor marketplace platform. "
            "I can help you with:\n\n"
            "- **Hosting an Event**: Creating events, scheduling agendas, and managing speakers.\n"
            "- **Ticketing & Multi-Currency**: Setting up free/paid tickets, promo codes, and fees.\n"
            "- **Instant Payouts & Gateways**: Paystack, Flutterwave, and Stripe Connect.\n"
            "- **Check-in & Digital Passes**: QR box office app and Apple Wallet passes.\n"
            "- **Vendor Marketplace**: Hiring caterers, photographers, security, and sound.\n"
            "- **Pricing & Plans**: Free forever tier, Growth ($19/mo), and Pro ($49/mo).\n\n"
            "What would you like to explore today?"
        )
        return {
            "reply": reply,
            "suggestions": ["How do I create an event?", "What are your fees?", "Can I hire vendors?", "What plans do you have?"]
        }

    # 2. Event Creation & Setup
    if re.search(r"\b(create|host|setup|start|publish|new)\s+(an?\s+)?event\b", q) or "how to create" in q or "host an event" in q:
        reply = (
            "### How to Create an Event on Heelo\n\n"
            "1. **Sign in or Create an Organization**: Head over to your dashboard or click **[Create Event](/events)**.\n"
            "2. **Event Details**: Enter your event title, format (*In-person*, *Virtual*, or *Hybrid*), dates, timezone, and venue/streaming link.\n"
            "3. **Setup Ticket Tiers**: Add Free, General, VIP, Early Bird, or Group tickets with your desired currency (*NGN, USD, GBP, EUR, KES, GHS, ZAR*).\n"
            "4. **Custom Agenda & Speakers**: Build your session timeline, tracks, stages, and add speaker profiles.\n"
            "5. **Marketing & Tracking**: Add your Meta, Google, or TikTok Pixel IDs for conversion tracking.\n"
            "6. **Publish & Sell**: Click **Publish** to get your public event page (e.g. `/e/your-event-slug`) and start accepting registrations immediately!"
        )
        return {
            "reply": reply,
            "suggestions": ["What are your fees?", "How do payouts work?", "Can I track ad conversions?"]
        }

    # 3. Pricing, Fees & Buyer Pass-through
    if re.search(r"\b(price|pricing|cost|fee|fees|percentage|charge|commission|rate)\b", q):
        reply = (
            "### Heelo Pricing & Fees\n\n"
            "- **Free Events**: **100% free, forever!** No ticket limits, no setup costs, and no forced upgrades.\n"
            "- **Paid Tickets**: Standard platform fee is **3.5% + processing**.\n"
            "- **Zero-Cost to Organizers**: By default, Heelo passes fees to the ticket buyer at checkout. That means **you keep 100% of your face-value ticket price**!\n"
            "- **Subscription Plans**:\n"
            "  - **Free Tier ($0/mo)**: Unlimited events, paid tickets, 1 team seat.\n"
            "  - **Growth ($19/mo or ₦7,500/mo)**: Custom branding, 3 team seats, recurring events, CRM import, custom form fields.\n"
            "  - **Pro ($49/mo or ₦25,000/mo)**: Sponsor management, live polls & Q&A, full analytics, custom domain.\n\n"
            "Check full plan comparisons on our **[Pricing Page](/pricing)**."
        )
        return {
            "reply": reply,
            "suggestions": ["How do payouts work?", "What is included in the Pro plan?", "How do I create an event?"]
        }

    # 4. Payouts, Gateways & Bank Transfers
    if re.search(r"\b(payout|payouts|withdraw|transfer|bank|paystack|flutterwave|stripe|money|revenue)\b", q):
        reply = (
            "### Payouts & Payment Gateways on Heelo\n\n"
            "Heelo provides multiple automated payout options to ensure organizers get paid quickly and securely:\n\n"
            "- **Instant Subaccount Splits**: Connect your Paystack, Flutterwave, or Stripe Connect subaccount in **[Payment Settings](/dashboard)**. Ticket funds automatically split and route directly into your bank account at charge time.\n"
            "- **Batch Payouts**: For standard accounts, Heelo runs automated batch payouts with **0% platform withholding**.\n"
            "- **Multi-Currency Settlements**: Accept payments in NGN, USD, GBP, EUR, KES, GHS, or ZAR depending on your country and gateway setup.\n"
            "- **Payment Methods**: Attendees can pay using debit/credit cards, bank transfers, Apple Pay, Google Pay, USSD, and Mobile Money."
        )
        return {
            "reply": reply,
            "suggestions": ["What are your fees?", "Do you support corporate invoices?", "Can I track ad conversions?"]
        }

    # 5. Check-in, Box Office, QR codes & Apple Wallet
    if re.search(r"\b(check[- ]?in|box office|scanner|qr|ticket|badge|wallet|pkpass|apple wallet)\b", q):
        reply = (
            "### Check-in, Box Office & Digital Wallet Passes\n\n"
            "- **High-Speed Box Office**: Use our web-based Box Office app at **`/check-in`**. Features automatic 5-second attendee list refresh, instant name search, and 1-tap check-in.\n"
            "- **Camera QR Scanner**: Built-in camera scanner reads signed cryptographic ticket QR codes in milliseconds.\n"
            "- **Offline Check-in**: Operates smoothly even with unstable venue internet using Service Worker offline synchronization.\n"
            "- **Apple Wallet Passes (.pkpass)**: Attendees receive an official **'Add to Apple Wallet'** pass on their confirmation page with date, venue, and live barcode.\n"
            "- **Thermal Badge Printing**: Print professional attendee name badges with QR codes directly from the dashboard."
        )
        return {
            "reply": reply,
            "suggestions": ["How do attendees receive tickets?", "How do I create an event?", "What are your fees?"]
        }

    # 6. Vendor Marketplace & Hiring
    if re.search(r"\b(vendor|vendors|cater|catering|photo|photographer|sound|dj|lighting|security|venue|hire|booth)\b", q):
        reply = (
            "### Heelo Vendor Marketplace (/vendors)\n\n"
            "Planning an event? You can discover and hire verified event professionals directly through Heelo:\n\n"
            "- **8 Core Categories**: Venues, Catering & Drinks, Photography & Video, Sound & DJ, Decor & Styling, Security & Bouncers, Event Hosts/MCs, Ushers & Protocol.\n"
            "- **Request a Quote (RFQ)**: Share your event date, location, and budget to receive custom proposals.\n"
            "- **Escrow Protection**: Your payment is safely held in escrow and only released when the vendor completes their milestones.\n"
            "- **Exhibition Booths**: Organizers can sell booth packages, and vendors can apply directly on event pages (`/events/[slug]/apply`).\n\n"
            "Explore verified professionals on the **[Vendor Marketplace](/vendors)**."
        )
        return {
            "reply": reply,
            "suggestions": ["How do I list as a vendor?", "What are your fees?", "How do payouts work?"]
        }

    # 7. Ad Tracking Pixels (Meta, Google, TikTok)
    if re.search(r"\b(pixel|pixels|meta|facebook|tiktok|google tag|gtm|ga4|tracking|conversion|ad)\b", q):
        reply = (
            "### Ad Conversion Tracking Pixels\n\n"
            "Heelo provides built-in integration for major advertising networks to measure campaign ROI:\n\n"
            "- **Meta (Facebook) Pixel**: Automatically fires `PageView` and `ViewContent` on event pages, and `Purchase` on checkout with exact revenue and currency.\n"
            "- **Google Tag / GTM / GA4**: Native gtag.js integration with `page_view` and `purchase` ecommerce transaction events.\n"
            "- **TikTok Pixel**: Tracks `ViewContent` and `CompletePayment` conversions from TikTok ads.\n\n"
            "**How to configure**: Open your event editor -> Expand **Tracking & Invoicing** -> Enter your Meta Pixel ID, Google Tag ID, or TikTok Pixel ID -> Save!"
        )
        return {
            "reply": reply,
            "suggestions": ["How do abandoned checkout recovery emails work?", "How do I create an event?", "What are your fees?"]
        }

    # 8. Abandoned Checkout Recovery
    if re.search(r"\b(abandon|abandoned|recovery|incomplete|resume|nudge|cart)\b", q):
        reply = (
            "### Automated Abandoned Checkout Recovery\n\n"
            "Heelo automatically recovers attendees who started purchasing tickets but left before completing payment:\n\n"
            "- **Automated Background Cron**: Runs every 15 minutes to identify unpaid checkouts between 20 minutes and 24 hours old.\n"
            "- **1-Click Resumption**: Attendees receive a branded email reminder with a direct link (`/orders/resume/[token]`) that restores their reservation and redirects them straight to payment.\n"
            "- **Inventory Protection**: If tickets sell out or the event is cancelled, the resumption link safely informs the attendee."
        )
        return {
            "reply": reply,
            "suggestions": ["Can I track ad conversions?", "How do payouts work?", "What are your fees?"]
        }

    # 9. Corporate Invoicing & VAT Compliance
    if re.search(r"\b(invoice|invoices|vat|tax|corporate|receipt|pdf|company)\b", q):
        reply = (
            "### Corporate Invoicing & VAT Compliance\n\n"
            "- **Organizer Tax Setup**: Organizers can enter their registered Tax Identification Number (TIN/VAT) and Tax Rate % in event settings.\n"
            "- **Corporate Checkout**: Business attendees can check 'Corporate Tax Invoice' during registration to provide their Company Name, Tax ID, and Billing Address.\n"
            "- **Instant PDF Invoices**: Attendees and corporate finance teams can download official, VAT-itemized PDF invoices from the confirmation page (`/orders/[id]/invoice.pdf`)."
        )
        return {
            "reply": reply,
            "suggestions": ["How do I create an event?", "What are your fees?", "What subscription plans exist?"]
        }

    # 10. Live Events & Recommendations
    if re.search(r"\b(what('?s)? happening|upcoming|events|find events|browse events|parties|concerts)\b", q):
        if live_context and "Live Upcoming Events" in live_context:
            reply = (
                f"### Upcoming Events on Heelo\n\n{live_context}\n\n"
                "You can browse all public events, filter by category or city, and reserve your tickets on the **[Explore Events Page](/events)**!"
            )
        else:
            reply = (
                "### Explore Events on Heelo\n\n"
                "Discover concerts, tech conferences, festivals, networking mixers, and workshops happening near you!\n\n"
                "Visit **[Discover Events](/events)** to search by keyword, city, category, or date."
            )
        return {
            "reply": reply,
            "suggestions": ["How do I register for an event?", "How do I create an event?", "Can I hire vendors?"]
        }

    # 11. Support & Human Contact
    if re.search(r"\b(support|contact|help|email|phone|human|agent|talk to someone|team)\b", q):
        reply = (
            "### Need Additional Assistance?\n\n"
            "Our team is always here to help:\n\n"
            "- **Email Support**: Reach us directly at **[hello@heelo.io](mailto:hello@heelo.io)**.\n"
            "- **Organizer Portal**: Manage your events, team members, and finances in the **[Dashboard](/dashboard)**.\n"
            "- **Response Time**: We typically respond within a few hours on business days."
        )
        return {
            "reply": reply,
            "suggestions": ["How do I create an event?", "What are your fees?", "How do payouts work?"]
        }

    # Generic Fallback with Project Knowledge
    extra_events = f"\n\n{live_context}" if live_context and "Live Upcoming Events" in live_context else ""
    reply = (
        f"**Heelo is the all-in-one event and vendor marketplace platform.**\n\n"
        f"Here are key things I can assist you with:\n"
        f"- **Event Creation & Scheduling**: Setting up in-person or virtual events with multi-tier tickets.\n"
        f"- **Ticketing & Multi-Currency**: Pricing tickets in NGN, USD, GBP, EUR, KES, GHS, ZAR with 0% fee pass-through to organizers.\n"
        f"- **Instant Payouts**: Automated subaccount split payments via Paystack, Flutterwave, and Stripe.\n"
        f"- **Check-in & Digital Passes**: Box office QR scanner and Apple Wallet passes.\n"
        f"- **Vendor Marketplace**: Hiring caterers, photographers, sound/DJ, and security with milestone escrow protection.\n"
        f"- **Subscription Plans**: Free ($0/mo), Growth ($19/mo), and Pro ($49/mo).{extra_events}\n\n"
        f"Could you tell me more about what you'd like to do?"
    )
    return {
        "reply": reply,
        "suggestions": ["How do I create an event?", "What are your fees?", "Can I hire vendors?", "How do payouts work?"]
    }


# ── Main Chat Generation Function ─────────────────────────────────────────────

async def get_chatbot_reply(
    *,
    db: AsyncSession,
    user_message: str,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Generate an AI response using Anthropic Claude if configured,
    or the high-accuracy rule-based knowledge engine fallback.
    """
    clean_message = (user_message or "").strip()
    if not clean_message:
        return {
            "reply": "How can I help you with Heelo today? Ask me about creating events, ticketing, payouts, or hiring vendors!",
            "suggestions": ["How do I create an event?", "What are your fees?", "Can I hire vendors?"]
        }

    # Fetch live database context (e.g. real upcoming events, vendor categories)
    live_context = ""
    try:
        live_context = await get_live_database_context(db, clean_message)
    except Exception as exc:
        logger.warning("chatbot.live_context_failed", error=str(exc))

    # If ANTHROPIC_API_KEY is configured, call Claude
    if settings.ANTHROPIC_API_KEY:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

            system_content = SYSTEM_KNOWLEDGE_PROMPT
            if live_context:
                system_content += f"\n\nLive Database Information for this Query:\n{live_context}"

            messages: list[dict[str, str]] = []
            if chat_history:
                # Include up to 6 recent conversation turns
                for m in chat_history[-6:]:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    if role in ("user", "assistant") and content:
                        messages.append({"role": role, "content": content})

            messages.append({"role": "user", "content": clean_message})

            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=system_content,
                messages=messages,
            )
            text_reply = response.content[0].text.strip()
            return {
                "reply": text_reply,
                "suggestions": [
                    "How do I create an event?",
                    "What are your fees?",
                    "How do payouts work?",
                    "Can I hire vendors?",
                ],
            }
        except Exception as exc:
            logger.warning("chatbot.anthropic_failed_fallback_to_rules", error=str(exc))
            # Fall back cleanly to the rule-based knowledge engine
            return get_rule_based_response(clean_message, live_context)

    # Offline / local development rule-based knowledge engine
    return get_rule_based_response(clean_message, live_context)

