# Tixdoo Landing Page - Audit, Positioning & Copy

This document is the source of truth behind the rebuilt `home/landing.html`. Every feature claim below was verified against the actual codebase (file:line evidence available on request) - nothing here is aspirational. Where something looked like a real feature but wasn't wired up end-to-end, it's flagged explicitly in **§1.3** and excluded from copy.

---

## 1. Codebase Audit

### 1.1 Feature inventory by domain

**Event creation**
- Full event CRUD: format (in-person/virtual/hybrid), venue, capacity, cover/gallery images, categories, vibe tags.
- AI-assisted description writing - a real, streaming Claude-powered generator wired directly into the creation form (`generate-event-description`), not a separate tool bolted on.
- Recurring events (daily/weekly/monthly), event templates/duplication (Growth+).

**Ticketing & payments**
- Ticket types: free, paid, VIP, early-bird, group - with capacity, min/max per order, sale-window scheduling.
- Promo codes (percent or fixed), waitlists with automatic offer-on-cancellation.
- Payments via Paystack (NGN, GHS, ZAR, KES, EGP), with Flutterwave and Stripe as configured fallbacks for other currencies - all three are real, live integrations, not stubs.
- Flat 5% platform fee, separate from payment gateway processing costs. **Organizer chooses who pays it**, per event: absorb it (default) or pass it, plus an estimated payment-processing fee, to the buyer at checkout. This is a genuine, working toggle, not a plan.
- Referral program: attendees get a shareable link; a referred friend gets 5% off, and the discount is absorbed by Tixdoo's fee first, not deducted from the organizer's payout.
- Real payout splitting to the organizer's own connected Paystack/Flutterwave subaccount (or a manually-recorded local account for reference).

**Check-in**
- QR camera scan and manual name/email/phone search.
- **Genuine offline mode** - not just "works on a phone browser." The kiosk is a real PWA: a service worker caches assets, queues failed check-in requests in IndexedDB, and drains them via the Background Sync API once connectivity returns, including surfacing sync-time duplicate conflicts. This is meaningfully more robust than "works on a phone."
- Live check-in stream (SSE, 5s).
- Badge PDFs (single + bulk print run) and post-event certificate PDFs for checked-in attendees - both real, working PDF generation, no external service.

**Marketing & CRM**
- WhatsApp campaigns and email campaigns with audience segmentation, respecting unsubscribes.
- A real Contact database (not just derived from ticket sales) with CSV import, tagging, and one-click unsubscribe compliance - Growth+ for import.
- WhatsApp ticket delivery: the QR code itself is sent as an image over WhatsApp, plus automated reminders and waitlist notifications - not just an email with a WhatsApp icon next to it.

**Live engagement (Pro+)**
- Live polls and audience Q&A with upvoting, updating on a 3-second live stream during the event itself.

**Conference tools**
- Reusable speaker profiles (bio, photo, socials) attachable across multiple events, with a genuine self-service invite-and-claim flow.
- Multi-track agenda/session builder with drag-reorder.
- Sponsor tiers (platinum → media) with a real self-service sponsor portal - sponsors claim an invite and edit their own logo/description.

**Vendor marketplace**
- A searchable public vendor directory (category, city, price range) with vendor self-service profiles and a lead-capture contact form. This is a discovery and leads tool - see §1.3 for what it is *not*.

**Analytics**
- Revenue and ticket-type breakdowns, UTM-attributed revenue, live check-in stream, CSV export.
- AI-generated insights: three plain-English takeaways (what's working, what's not, one thing to try) generated from the event's real numbers.

**Integrations**
- Public REST API (read event/registration data, plus programmatic check-in) and signed webhooks, both with real API-key auth and HMAC signing.
- Custom domain support (Pro+), SSO for Google Workspace domains (Enterprise), full white-label removal of Tixdoo branding (Enterprise).

**Team & plans**
- Role-based team seats (admin/organizer/finance/check-in staff), 24-hour invite links with one-click resend.
- Four tiers - Free / Growth / Pro / Enterprise - self-serve checkout for Growth and Pro, admin-provisioned for Enterprise.

### 1.2 Discovery UI - worth calling out on its own

`home/discover.html` is a vertical, scroll-snap, one-card-at-a-time event feed - a real TikTok/Reels-style browsing experience, not a generic grid or list. This is a genuine, distinctive piece of the product and is used in the copy below.

### 1.3 Explicitly NOT used in copy (verified incomplete or unwired)

| Looked like | What's actually true |
|---|---|
| "Conversational AI event creation" | Not built. What's real is AI-assisted *description writing* inside the normal creation form - useful, but not a chat-driven builder. |
| "Gamified check-in" (points/leaderboards) | Not built at all. No trace of it anywhere in the models or services. |
| "Map-first discovery" | Not built. Individual event pages link out to Google Maps; there's no in-app map browsing view. Discovery is genuinely feed-first (see §1.2), not map-first. |
| "Attendance heatmap" | Not built - this was already aspirational copy sitting in the *old* landing page with zero backing code. Removed. |
| "AI-powered WhatsApp replies" | The code exists (`suggest_whatsapp_reply_sync` + a Celery task) but is never called from the live webhook path. The bot that actually runs is keyword-based only. Do not claim AI here. |
| Full webhook event catalog | Seven event types are defined; only `order.paid` and `checkin.completed` are ever actually fired. Copy only claims what fires. |
| Vendor marketplace as a monetized/commission marketplace | No commission, fee, or payment code exists anywhere in the vendor flow. It's framed as discovery + leads, not "Tixdoo takes a cut." |
| "Vetted" or "verified" vendors | Vendors go live immediately on self-signup; admin moderation is reactive (suspend after the fact), not a pre-listing approval queue. |
| Public API as full integration platform | It's read-mostly plus one write action (check-in). Copy says "pull your data and check attendees in programmatically," not "build anything on Tixdoo." |

---

## 2. Differentiation - what's genuinely distinctive vs. Tix Africa / Selar-style platforms

Generic Nigerian ticketing platforms are, at their core, ticketing-first: create an event, sell a ticket, scan a QR code. Tixdoo's real differentiation, backed by the audit above:

1. **WhatsApp as a first-class channel, not an afterthought.** Tickets are delivered as WhatsApp images, not just email. Reminders, waitlist offers, and campaigns all run through WhatsApp with real opt-out compliance.
2. **Offline check-in that actually survives no signal.** A real service worker + IndexedDB queue + background sync - built for venues where the WiFi is the least reliable part of the event, which is most venues.
3. **You decide who eats the fee.** Absorb Tixdoo's 5% and the processing fee yourself, or pass both to the buyer at checkout, a per-event switch, not a fixed platform-wide policy.
4. **A conference toolkit most ticketing platforms don't have.** Speakers, multi-track agendas, and a self-service sponsor portal - built for summits and conferences, not just concerts and parties.
5. **AI where it actually saves time.** Event descriptions, campaign copy, and post-event analytics summaries are generated in the workflow itself, not a separate "AI tools" tab you have to remember exists.
6. **A referral loop that costs the organizer nothing.** Every attendee gets a shareable link; Tixdoo's own fee absorbs the referral discount first.
7. **A discovery feed people actually scroll.** Vertical, one-event-at-a-time browsing, not a static list of upcoming events nobody opens twice.

---

## 3. Landing Page Copy

### 3.1 Hero

**Headline:**
# Tickets your guests actually open.

**Subheadline:**
Tixdoo sends tickets straight to WhatsApp, settles payouts to your Paystack or Flutterwave account, and keeps check-in running even when the venue WiFi gives up. Built for organizers running real events in Nigeria - not a platform that happens to work here.

**CTA:** `Start free - no card required` · `See how it works`

---

### 3.2 Problem / Promise

**Eyebrow:** The gap between "sold a ticket" and "ran a good event"

**Heading:**
## Your guests don't check email. Your venue doesn't have WiFi. Your fee shouldn't be a mystery.

**Body:**
Most ticketing platforms were built somewhere else and shipped here unchanged - email confirmations nobody opens, check-in apps that fall over the moment the signal drops, and a payout structure you find out about after the money's already moved.

Tixdoo starts from what actually happens at a Nigerian event: your guests live on WhatsApp, your gate staff need check-in to work with or without signal, and you should know exactly what you're taking home before you publish a single ticket. That's not a feature list - it's the whole design.

---

### 3.3 Feature Highlights

**Eyebrow:** What's actually in the box

**Heading:**
## Everything between "create event" and "see you next time."

1. **WhatsApp-native tickets** - QR tickets, reminders, and waitlist offers land where your guests actually read messages, no app download required.
2. **Check-in that doesn't care about signal** - scan or search offline, and every check-in syncs automatically the moment connectivity comes back.
3. **You choose who pays the fee**: absorb Tixdoo's 5% and processing costs yourself, or pass them to the buyer at checkout, per event.
4. **Real conference tools, not just ticket scanning** - speaker profiles, multi-track agendas, and a self-service sponsor portal for summits that outgrow a spreadsheet.
5. **AI baked into the actual workflow** - write your event description, your campaign message, and get a plain-English read on how the event went, without leaving the page you're already on.
6. **A referral loop that pays for itself** - every attendee gets a link to share; friends get 5% off, and it never comes out of your payout.

---

### 3.4 Pricing Teaser

**Eyebrow:** Pricing

**Heading:**
## Start free. Upgrade when you actually need to.

- **Free - ₦0/mo.** Unlimited events and paid tickets, one seat, QR check-in, kiosk mode, certificates. No trial clock, no forced upgrade.
- **Growth - ₦7,500/mo.** Your branding everywhere, 3 team seats, CRM import, unlimited promo codes, speakers & agenda.
- **Pro - ₦25,000/mo.** Sponsors, live polls & Q&A, full analytics, a custom domain, 10 team seats.
- **Enterprise - custom.** SSO, full white-label, unlimited seats, and a dedicated account manager.

**CTA:** `See full pricing →`

*(Numbers pulled directly from `app/services/billing_service.py` / `app/plans.py` - current as of this build.)*

---

### 3.5 Social Proof - PLACEHOLDER

> **This section is a marked placeholder.** No real testimonials, logos, or usage numbers exist yet - do not publish fabricated quotes or made-up organizer names. Replace this block with real attributed quotes, event logos, or a genuine usage stat (e.g. "X events run on Tixdoo") the moment you have them. Until then, the built page below ships with a quiet, honest "early access" framing instead of fake social proof.

---

### 3.6 Final CTA

**Heading:**
## Your next event doesn't need five different tools.

**Body:** Create your first event free. No card required, no time limit on the free plan.

**CTA:** `Create your first event →`

---

## 4. UI Direction

**Keeping as-is (per your instruction):** the existing design system - `--cyan: #00FFF3` as the single accent against near-black (`#0A0A0A`) and warm off-white (`#F7F7F5`), Lora for display/serif headings, Geist for body/UI text, JetBrains Mono for anything code-like. No new tokens introduced.

**Layout structure** (simplified from the previous landing page, which had grown to 8+ sections - this rebuild is the 6 sections above, in order, and nothing else):

1. **Nav** - sticky, blurred-glass on scroll (kept from the existing page - it already works well).
2. **Hero** - light background, serif headline with the single cyan-accented word, product-preview mockup below the fold-line CTA (kept - it's a strong, real conversion element and directly shows the product rather than describing it).
3. **Problem/Promise** - a full-bleed dark section (near-black), breaking the rhythm of the light sections around it, so the "here's what's actually broken" framing feels like a deliberate pause, not more of the same scroll.
4. **Feature highlights** - back to light, a clean 2-column (mobile: 1-column) grid of 6 cards, each with a small icon tile, not a wall of 25+ marquee pills like the previous version. Simplicity over exhaustiveness.
5. **Pricing teaser** - 4-column card row (mobile: stacked), the current/popular-tier visual treatment already established in `dashboard/plan.html` reused here for consistency between marketing and in-app pricing.
6. **Social proof placeholder** - visually quiet, a single centered strip, clearly a placeholder (not styled to look like fake testimonials).
7. **Final CTA** - dark, full-bleed, oversized serif heading, single button. Kept from the existing page's CTA section treatment.
8. **Footer** - kept as-is, minimal.

**What's being cut from the previous version, deliberately:** the feature-name marquee wall, the separate "Integrations" grid, the "How it works" 3-step section, and the API code-snippet window. These were well-crafted but pushed the page past "simple," and none of them were in your requested 6-section structure. The code window in particular oversold the API's real scope (§1.3) - better dropped than reworked.

**Motion:** minimal, intentional - nav blur-on-scroll and card hover lifts (both already implemented, kept), no new scroll-triggered animation added. `prefers-reduced-motion` respected throughout.
