# Comprehensive Search & Generative Engine Optimization (SEO/GEO/AEO) Report

**Platform**: Heelo Event Ticketing, Intelligence & Marketplace  
**Date**: October 21, 2026  
**Roles**: Senior Technical SEO Engineer, Search Strategy Specialist, Generative Engine Optimization Specialist, Answer Engine Optimization Specialist, Structured Data Engineer, Web Performance Engineer, Full-Stack Developer  
**Status**: Implemented, Hardened & Automated Tests Verified (100% Green Baseline)  

---

## Executive Summary

A comprehensive, production-ready search and generative engine optimization strategy was executed across the Heelo platform. Every technical, on-page, programmatic, and structured data improvement was implemented directly in the application codebase, verified with automated tests, and tested against live endpoint responses.

---

## 1. Technical SEO Audit & Implemented Improvements

| Phase | Focus Area | Status | Verification Summary |
| :--- | :--- | :---: | :--- |
| **Phase 1** | Technical SEO & Crawlability | `VERIFIED` | Hardened `/robots.txt` disallows sensitive paths; `/sitemap.xml` updated. |
| **Phase 2** | URL Architecture & Canonicalization | `VERIFIED` | Clean programmatic `/events/category/{slug}` and `/events/city/{slug}` routes. |
| **Phase 3** | Dynamic On-Page Metadata | `VERIFIED` | Dynamic contextual `<title>`, meta descriptions, Open Graph & Twitter cards. |
| **Phase 4** | Schema.org Structured Data | `VERIFIED` | Valid JSON-LD for `Event`, `WebSite`, `Organization`, `LocalBusiness`, `Person`, `FAQPage`, `BreadcrumbList`, and `ItemList`. |
| **Phase 5** | Crawling, Indexing & Sitemaps | `VERIFIED` | Comprehensive XML sitemap with image extensions, daily/weekly change frequencies, and dynamic city/category discovery. |
| **Phase 6** | Programmatic SEO | `VERIFIED` | Clean category and city hubs with canonical consolidation preventing duplicate query string index bloat. |
| **Phase 7** | Local SEO & Geo Discovery | `VERIFIED` | Physical `Place` & `PostalAddress` schema on offline events, `VirtualLocation` on virtual events. |
| **Phase 8** | Generative Engine Optimization (GEO) | `VERIFIED` | Unambiguous factual data representation, clear entity relationships, AI bot crawl permissions. |
| **Phase 9** | Answer Engine Optimization (AEO) | `VERIFIED` | Real platform FAQPage schema on homepage and pricing pages for direct answers. |
| **Phase 10** | Content & Internal Linking | `VERIFIED` | Breadcrumb chains across all primary public discovery surfaces. |
| **Phase 11** | Privacy & Index Protection | `VERIFIED` | Strict `noindex, follow` on auth flows and `noindex, nofollow` on attendee order confirmations and payment pages. |
| **Phase 12** | Core Web Vitals & Performance | `VERIFIED` | `fetchpriority="high"` on LCP hero media; `loading="lazy"` and `decoding="async"` on all secondary imagery. |
| **Phase 13** | Automated Regression Suite | `VERIFIED` | 17 dedicated automated tests in `tests/test_seo.py` passing with 100% green status. |

---

## 2. Robots.txt & Crawling Policy

Located at `/robots.txt` ([`app/routers/pages.py`](file:///Users/aflame/heelo/app/routers/pages.py)):

```text
User-agent: *
Disallow: /dashboard
Disallow: /admin
Disallow: /org/
Disallow: /api/
Disallow: /my-tickets
Disallow: /my-vendor-profile
Disallow: /my-vendor-dashboard
Disallow: /my-bookings
Disallow: /my-sponsorships
Disallow: /messages
Disallow: /onboarding
Disallow: /orders/
Disallow: /payments/
Disallow: /billing/
Disallow: /booths/
Disallow: /feedback/
Disallow: /transfer/
Disallow: /unsubscribe/
Disallow: /sponsor-invite/
Disallow: /accept-invite/

# Allow public search and discovery
Allow: /
Allow: /events
Allow: /venues
Allow: /vendors
Allow: /pricing
Allow: /host
Allow: /discover
Allow: /e/
Allow: /speakers/
Allow: /p/
Allow: /static/

Sitemap: https://heelo.io/sitemap.xml
```

### Privacy & Anti-Leak Protection
- Private attendee order confirmations (`/orders/{order_id}/confirmation`) are disallowed in `robots.txt` and fortified with `<meta name="robots" content="noindex, nofollow" />`.
- Internal financial callbacks, booking payments, and attendee feedback links are prevented from polluting search engine indexes.
- Utility authentication routes (`/login`, `/register`, `/forgot-password`, `/reset-password`, `/verify`, `/role`) include `<meta name="robots" content="noindex, follow" />` so search crawlers can discover public links without indexing utility input forms.
- Private events (`is_private == True`) dynamically render `<meta name="robots" content="noindex, nofollow" />` and are excluded from XML sitemaps.

---

## 3. Dynamic XML Sitemap Configuration

Located at `/sitemap.xml` ([`app/routers/pages.py`](file:///Users/aflame/heelo/app/routers/pages.py)):

Features:
- XML Namespace: `xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"` and Google Image extension `xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"`.
- Static Core Surfaces: `/` (1.0 daily), `/events` (0.9 daily), `/discover` (0.8 daily), `/venues` (0.8 weekly), `/vendors` (0.8 weekly), `/pricing` (0.8 monthly), `/host` (0.8 monthly), `/terms` (0.3 yearly), `/privacy` (0.3 yearly).
- Programmatic Event Categories: Dynamically enumerates active categories (`/events/category/{slug}`).
- Programmatic Event Cities: Dynamically selects distinct cities from published events (`/events/city/{city_slug}`).
- Published Events: Dynamically lists all public, non-draft, non-deleted events with `lastmod`, `priority="0.8"` for scheduled events, and `<image:image>` metadata for event banner indexing.
- Verified Vendors & Venues: Dynamically lists public profiles with `lastmod` and image metadata.
- Featured Speakers: Dynamically queries speakers linked to active public events.

---

## 4. Structured Data (Schema.org) Implementation

### 4.1 Event Schema & Breadcrumbs (`app/templates/events/public.html`)
- **Type**: `Event`
- **Properties**:
  - `name`: Event title
  - `description`: Event summary
  - `startDate` & `endDate`: ISO-8601 timestamps
  - `eventAttendanceMode`: Dynamically evaluates `OnlineEventAttendanceMode`, `MixedEventAttendanceMode`, or `OfflineEventAttendanceMode`
  - `eventStatus`: Dynamically evaluates `EventScheduled`, `EventCancelled`, `EventPostponed`, or `EventRescheduled`
  - `inLanguage`: `"en"`
  - `location`: Structured `Place` with `PostalAddress` (street, locality, country) for in-person events; `VirtualLocation` with stream URL for online events
  - `organizer`: Structured `Organization` with name, public URL, and brand logo
  - `performer`: Structured array of `Person` entities when speakers are assigned to the event
  - `isAccessibleForFree`: Boolean dynamically determined by presence of free ticket tiers
  - `offers`: Structured array of `Offer` items with name, price, currency, availability (`InStock` vs `SoldOut`), and registration URL
- **BreadcrumbList**: Position 1: Home (`/`) -> Position 2: Events (`/events`) -> Position 3: Event Title (`/e/{slug}`)

### 4.2 WebSite, Organization & FAQ Schema (`app/templates/home/landing.html`)
- **WebSite**: Declares Sitelinks Searchbox (`SearchAction` targeting `/events?q={search_term_string}`).
- **Organization**: Declares Heelo brand identity, official logo, and platform scope.
- **FAQPage**: Encodes verified platform answers (ticket verification, transfer policies, automated payouts, multi-currency options).

### 4.3 Pricing Schema (`app/templates/marketing/pricing.html`)
- **BreadcrumbList**: Home -> Pricing
- **FAQPage**: Encodes fee models (free events are free, pass fees to buyer vs absorb, refund policy).

### 4.4 Vendor & Venue Schema (`app/templates/vendors/detail.html` & `list.html`)
- **LocalBusiness**: Name, description, image, phone, postal address, and dynamic price range symbols.
- **BreadcrumbList**: Home -> Vendors/Venues -> Business Profile.

### 4.5 Speaker Profile Schema (`app/templates/speakers/profile.html`)
- **Person**: Name, job title, company (`worksFor`), description, photo, public URL, social profile links (`sameAs`), and active events (`performerIn`).
- **BreadcrumbList**: Home -> Events -> Speaker Name.

### 4.6 Public User Profile Schema (`app/templates/user/public_profile.html`)
- **ProfilePage**: Declares person entity with name, handle, avatar, and URL.

---

## 5. Programmatic SEO & Canonical Clean URLs

To prevent query parameter duplicate content penalties while maximizing targeted search reach, programmatic routes were implemented in [`app/routers/pages.py`](file:///Users/aflame/heelo/app/routers/pages.py):

1. **Category Landing Hubs**:
   - URL Pattern: `/events/category/{category_slug}` (e.g. `/events/category/tech`, `/events/category/music`)
   - Canonical URL: `https://heelo.io/events/category/{category_slug}`
   - Dynamic Title: `Tech Events | Discover Upcoming Tech Conferences and Meetups | Heelo`
   - Dynamic Meta: Contextual summary of category events with clear call to action
   - Structured Data: `BreadcrumbList` and `ItemList` containing top 20 events in that category

2. **City Landing Hubs**:
   - URL Pattern: `/events/city/{city_slug}` (e.g. `/events/city/lagos`, `/events/city/london`)
   - Canonical URL: `https://heelo.io/events/city/{city_slug}`
   - Dynamic Title: `Events in Lagos | Discover Top Events, Festivals and Concerts | Heelo`
   - Dynamic Meta: Location-specific event discovery copy
   - Structured Data: `BreadcrumbList` and `ItemList` containing top 20 events in that city

3. **Canonical Consolidation**:
   - In [`app/templates/base.html`](file:///Users/aflame/heelo/app/templates/base.html), canonical URLs default to clean paths and consume `custom_canonical` whenever a filtered view is accessed.
   - Searching or filtering by category on `/events?category=tech` automatically sets `<link rel="canonical" href="https://heelo.io/events/category/tech">`, funneling ranking signals to the canonical category page.

---

## 6. Core Web Vitals & Web Performance Hardening

1. **Largest Contentful Paint (LCP)**:
   - Event hero banner in [`app/templates/events/public.html`](file:///Users/aflame/heelo/app/templates/events/public.html#L919) has `fetchpriority="high"` and `decoding="async"`, instructing the browser to prioritize the hero image during initial resource scheduling.
2. **First Input Delay (FID) / Interaction to Next Paint (INP)**:
   - External library scripts (`htmx`, `alpine.js`) load with `defer` attributes, preventing render-blocking during main-thread execution.
3. **Cumulative Layout Shift (CLS)**:
   - Secondary images (gallery pictures, vendor cards, avatars) utilize `loading="lazy" decoding="async"` with explicit CSS aspect ratios to preserve layout geometry during progressive image loading.
4. **Font Optimization**:
   - Google Fonts preconnect directives with `&display=swap` configured in [`app/templates/base.html`](file:///Users/aflame/heelo/app/templates/base.html#L68) to prevent font-swap layout flashes.

---

## 7. External Account Setup & Verification Checklist

To complete search engine verification in production:

1. **Google Search Console**:
   - Register domain property for `heelo.io`.
   - Set the `GOOGLE_SITE_VERIFICATION` environment variable in your production `.env` (or via DNS TXT record). Heelo will automatically render `<meta name="google-site-verification" content="...">` in [`base.html`](file:///Users/aflame/heelo/app/templates/base.html#L31).
   - Submit sitemap index: `https://heelo.io/sitemap.xml`.
2. **Bing Webmaster Tools**:
   - Import verification directly from Google Search Console.
   - Confirm sitemap discovery of `https://heelo.io/sitemap.xml`.
3. **Google Analytics (GA4)**:
   - Create a GA4 property and retrieve the Measurement ID (format: `G-XXXXXXXXXX`).
   - Set `GA_MEASUREMENT_ID=G-XXXXXXXXXX` in `.env`.
   - Heelo's built-in GDPR/cookie consent banner automatically controls Google Tag consent states (`analytics_storage` and `ad_storage`).

