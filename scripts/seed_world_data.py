"""
Seed script to generate 20 international events across diverse countries with cover images,
and 10 complete international vendor profiles with full services, portfolios, and reviews.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.event import Event, EventCategory
from app.models.ticketing import TicketType
from app.models.vendor import Vendor, VendorServiceListing, VendorReview
from app.utils.auth import hash_password

async def seed_world_events_and_vendors():
    async with AsyncSessionLocal() as db:
        print("Starting global seed for 20 events and 10 vendors...")

        # 1. Fetch or create admin / host users
        admin = await db.scalar(select(User).where(User.email == "admin@tixdoo.com"))
        if not admin:
            admin = await db.scalar(select(User).limit(1))
            if not admin:
                print("No user found in database. Aborting.")
                return

        # 2. Setup international host organizations
        orgs_meta = [
            {
                "name": "Global Summit Collective",
                "slug": "global-summit-collective",
                "country": "GB",
                "currency": "GBP",
                "desc": "Premier international organizer for world conferences, leadership summits, and forums.",
            },
            {
                "name": "Vanguard Creative Labs",
                "slug": "vanguard-creative-labs",
                "country": "US",
                "currency": "USD",
                "desc": "Curators of cutting-edge creative arts, tech showcases, and interactive festivals.",
            },
            {
                "name": "AfroFutura Festivals",
                "slug": "afrofutura-festivals",
                "country": "KE",
                "currency": "KES",
                "desc": "Celebrating continental innovation, soundscapes, and cultural excellence across Africa.",
            },
        ]

        host_orgs = {}
        for om in orgs_meta:
            existing_org = await db.scalar(select(Organization).where(Organization.slug == om["slug"]))
            if not existing_org:
                existing_org = Organization(
                    owner_id=admin.id,
                    name=om["name"],
                    slug=om["slug"],
                    description=om["desc"],
                    brand_color="#00C896",
                    country=om["country"],
                    currency=om["currency"],
                    plan="pro",
                    is_active=True,
                )
                db.add(existing_org)
                await db.flush()

                member = OrganizationMember(
                    org_id=existing_org.id,
                    user_id=admin.id,
                    invited_email=admin.email,
                    role="admin",
                    invited_at=datetime.now(timezone.utc),
                    accepted_at=datetime.now(timezone.utc),
                    status="active",
                )
                db.add(member)
                await db.flush()
                print(f"Created organization: {existing_org.name}")
            host_orgs[om["slug"]] = existing_org

        # Fallback org if needed
        primary_org = host_orgs["global-summit-collective"]

        # Cache existing categories
        cats_list = (await db.scalars(select(EventCategory))).all()
        cats_by_slug = {c.slug: c for c in cats_list}

        # 3. Define 20 international events across diverse countries
        now = datetime.now(timezone.utc)
        events_data = [
            {
                "slug": "london-ai-cloud-summit-2026",
                "title": "London AI & Cloud Architecture Summit 2026",
                "org_slug": "global-summit-collective",
                "category_slug": "technology",
                "cover_url": "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1200&auto=format&fit=crop&q=80",
                "description": "Join 3,000 engineering leaders, cloud architects, and AI researchers at ExCeL London for keynotes on generative infrastructure, distributed systems, and LLM orchestration.",
                "format": "in_person",
                "city": "London",
                "country": "GB",
                "venue_name": "ExCeL London",
                "venue_address": "Royal Victoria Dock, 1 Western Gateway, London E16 1XL",
                "tz": "Europe/London",
                "lat": 51.5085,
                "lng": 0.0289,
                "days_ahead": 14,
                "duration_hours": 8,
                "capacity": 3000,
                "vibe_tags": ["Tech Keynotes", "Networking", "Deep Tech"],
                "currency": "GBP",
                "tickets": [
                    {"name": "Standard Access", "price": 149.00, "tier": "paid", "qty": 1500},
                    {"name": "VIP & Speaker Dinner Pass", "price": 499.00, "tier": "vip", "qty": 300},
                ],
            },
            {
                "slug": "manhattan-fintech-web3-forum-2026",
                "title": "Manhattan Fintech & Web3 Forum 2026",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "finance",
                "cover_url": "https://images.unsplash.com/photo-1591115765373-5207764f72e7?w=1200&auto=format&fit=crop&q=80",
                "description": "The definitive gathering of institutional allocators, quantitative traders, decentralized protocol founders, and banking innovators in the heart of New York.",
                "format": "hybrid",
                "city": "New York",
                "country": "US",
                "venue_name": "Javits Center",
                "venue_address": "429 11th Ave, New York, NY 10001",
                "tz": "America/New_York",
                "lat": 40.7580,
                "lng": -74.0022,
                "days_ahead": 21,
                "duration_hours": 9,
                "capacity": 2500,
                "vibe_tags": ["Fintech", "Wall Street", "Web3"],
                "currency": "USD",
                "tickets": [
                    {"name": "General Delegate", "price": 299.00, "tier": "paid", "qty": 1000},
                    {"name": "Virtual Stream Access", "price": 49.00, "tier": "paid", "qty": 2000},
                ],
            },
            {
                "slug": "silicon-savannah-tech-week-2026",
                "title": "Silicon Savannah Tech Week 2026",
                "org_slug": "afrofutura-festivals",
                "category_slug": "startup-innovation",
                "cover_url": "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1200&auto=format&fit=crop&q=80",
                "description": "Nairobi's premier multi-day celebration of African venture ecosystems, mobile commerce breakthroughs, and founder masterclasses at the Sarit Expo Centre.",
                "format": "in_person",
                "city": "Nairobi",
                "country": "KE",
                "venue_name": "Sarit Expo Centre",
                "venue_address": "Pio Gama Pinto Rd, Westlands, Nairobi",
                "tz": "Africa/Nairobi",
                "lat": -1.2612,
                "lng": 36.8028,
                "days_ahead": 10,
                "duration_hours": 7,
                "capacity": 1800,
                "vibe_tags": ["Founders", "African Tech", "Investors"],
                "currency": "KES",
                "tickets": [
                    {"name": "Founder Pass", "price": 4500.00, "tier": "paid", "qty": 800},
                    {"name": "Student / Scholar Pass", "price": 0.00, "tier": "free", "qty": 300},
                ],
            },
            {
                "slug": "afro-beats-highlife-sunset-festival-accra",
                "title": "Afro Beats & Highlife Sunset Festival",
                "org_slug": "afrofutura-festivals",
                "category_slug": "music",
                "cover_url": "https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=1200&auto=format&fit=crop&q=80",
                "description": "Experience live performances from West Africa's biggest chart-topping artists right on Laboma Beach in Accra. Food villages, live art installations, and oceanfront stages.",
                "format": "in_person",
                "city": "Accra",
                "country": "GH",
                "venue_name": "Laboma Beach Resort",
                "venue_address": "Laboma Beach, Teshie Rd, Accra",
                "tz": "Africa/Accra",
                "lat": 5.5700,
                "lng": -0.1200,
                "days_ahead": 18,
                "duration_hours": 10,
                "capacity": 5000,
                "vibe_tags": ["Afrobeats", "Live Concert", "Beach Party"],
                "currency": "GHS",
                "tickets": [
                    {"name": "General Admission", "price": 180.00, "tier": "paid", "qty": 3500},
                    {"name": "Golden Cabana VIP", "price": 850.00, "tier": "vip", "qty": 200},
                ],
            },
            {
                "slug": "africa-green-growth-climate-summit-kigali",
                "title": "Africa Green Growth & Climate Summit",
                "org_slug": "global-summit-collective",
                "category_slug": "business",
                "cover_url": "https://images.unsplash.com/photo-1587825140708-dfaf72ae4b04?w=1200&auto=format&fit=crop&q=80",
                "description": "Policymakers, renewable energy developers, and climate venture capitalists gather under the iconic dome of the Kigali Convention Centre to accelerate regional net-zero transitions.",
                "format": "in_person",
                "city": "Kigali",
                "country": "RW",
                "venue_name": "Kigali Convention Centre",
                "venue_address": "KG 2 Roundabout, Kimihurura, Kigali",
                "tz": "Africa/Kigali",
                "lat": -1.9536,
                "lng": 30.0934,
                "days_ahead": 28,
                "duration_hours": 8,
                "capacity": 1200,
                "vibe_tags": ["Sustainability", "CleanTech", "Government"],
                "currency": "USD",
                "tickets": [
                    {"name": "Delegate Pass", "price": 195.00, "tier": "paid", "qty": 600},
                    {"name": "Virtual Broadcast", "price": 0.00, "tier": "free", "qty": 2000},
                ],
            },
            {
                "slug": "cape-town-electronic-arts-festival-2026",
                "title": "Cape Town Electronic Music & Arts Festival",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "concerts-live-shows",
                "cover_url": "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1200&auto=format&fit=crop&q=80",
                "description": "An electric open-air celebration overlooking Table Mountain and the Atlantic Ocean. Curated international DJs, immersive projection mapping, and South African deep house.",
                "format": "in_person",
                "city": "Cape Town",
                "country": "ZA",
                "venue_name": "Grand Africa Café & Beach",
                "venue_address": "1 Haul Rd, V&A Waterfront, Cape Town 8001",
                "tz": "Africa/Johannesburg",
                "lat": -33.9015,
                "lng": 18.4230,
                "days_ahead": 12,
                "duration_hours": 11,
                "capacity": 2200,
                "vibe_tags": ["Deep House", "Table Mountain", "Dance"],
                "currency": "ZAR",
                "tickets": [
                    {"name": "Sunset Early Pass", "price": 380.00, "tier": "paid", "qty": 800},
                    {"name": "VIP Table Deck", "price": 1200.00, "tier": "vip", "qty": 150},
                ],
            },
            {
                "slug": "paris-contemporary-fashion-design-expo",
                "title": "Paris Contemporary Fashion & Design Expo",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "arts-culture",
                "cover_url": "https://images.unsplash.com/photo-1509631179647-0177331693ae?w=1200&auto=format&fit=crop&q=80",
                "description": "Exhibition of avant-garde haute couture, sustainable textile laboratories, and independent designer showcases inside Palais Brongniart in Paris.",
                "format": "in_person",
                "city": "Paris",
                "country": "FR",
                "venue_name": "Palais Brongniart",
                "venue_address": "Place de la Bourse, 75002 Paris",
                "tz": "Europe/Paris",
                "lat": 48.8687,
                "lng": 2.3413,
                "days_ahead": 16,
                "duration_hours": 7,
                "capacity": 1500,
                "vibe_tags": ["Fashion", "Runway", "Haute Couture"],
                "currency": "EUR",
                "tickets": [
                    {"name": "Exhibition Day Pass", "price": 65.00, "tier": "paid", "qty": 1000},
                    {"name": "Runway Front Row VIP", "price": 280.00, "tier": "vip", "qty": 120},
                ],
            },
            {
                "slug": "berlin-underground-electronic-soundscape",
                "title": "Berlin Underground Electronic Soundscape",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "nightlife-parties",
                "cover_url": "https://images.unsplash.com/photo-1516450360452-9312f5e86fc7?w=1200&auto=format&fit=crop&q=80",
                "description": "A 16-hour continuous industrial audio-visual odyssey featuring pioneer techno producers, analog modular synthesizers, and spatial acoustic architecture inside Funkhaus Berlin.",
                "format": "in_person",
                "city": "Berlin",
                "country": "DE",
                "venue_name": "Funkhaus Berlin",
                "venue_address": "Nalepastraße 18, 12459 Berlin",
                "tz": "Europe/Berlin",
                "lat": 52.4842,
                "lng": 13.5015,
                "days_ahead": 9,
                "duration_hours": 16,
                "capacity": 2000,
                "vibe_tags": ["Techno", "Underground", "Modular"],
                "currency": "EUR",
                "tickets": [
                    {"name": "General Entry Pass", "price": 38.00, "tier": "paid", "qty": 1500},
                ],
            },
            {
                "slug": "tokyo-robotics-autonomous-systems-expo",
                "title": "Tokyo Robotics & Autonomous Systems Expo",
                "org_slug": "global-summit-collective",
                "category_slug": "technology",
                "cover_url": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=1200&auto=format&fit=crop&q=80",
                "description": "Witness humanoids, autonomous logistics drones, and cutting-edge cybernetic demonstrations by Japan and East Asia's leading laboratory institutes at Tokyo Big Sight.",
                "format": "in_person",
                "city": "Tokyo",
                "country": "JP",
                "venue_name": "Tokyo Big Sight",
                "venue_address": "3 Chome-11-1 Ariake, Koto City, Tokyo 135-0063",
                "tz": "Asia/Tokyo",
                "lat": 35.6298,
                "lng": 139.7942,
                "days_ahead": 24,
                "duration_hours": 8,
                "capacity": 4000,
                "vibe_tags": ["Robotics", "Future Tech", "Tokyo"],
                "currency": "USD",
                "tickets": [
                    {"name": "Visitor Expo Ticket", "price": 40.00, "tier": "paid", "qty": 2500},
                    {"name": "Technical Session Pass", "price": 180.00, "tier": "paid", "qty": 500},
                ],
            },
            {
                "slug": "dubai-luxury-hospitality-gourmet-gala",
                "title": "Dubai Luxury Hospitality & Gourmet Gala",
                "org_slug": "global-summit-collective",
                "category_slug": "food-drink",
                "cover_url": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1200&auto=format&fit=crop&q=80",
                "description": "An ultra-exclusive seven-course tasting journey orchestrated by five Michelin-starred guest chefs with skyline views of Downtown Dubai and the Burj Khalifa fountains.",
                "format": "in_person",
                "city": "Dubai",
                "country": "AE",
                "venue_name": "Armani Hotel Dubai",
                "venue_address": "Burj Khalifa, 1 Sheikh Mohammed bin Rashid Blvd, Downtown Dubai",
                "tz": "Asia/Dubai",
                "lat": 25.1972,
                "lng": 55.2744,
                "days_ahead": 15,
                "duration_hours": 5,
                "capacity": 450,
                "vibe_tags": ["Fine Dining", "Luxury", "Michelin"],
                "currency": "AED",
                "tickets": [
                    {"name": "Gourmet Gala Ticket", "price": 1250.00, "tier": "paid", "qty": 350},
                    {"name": "Private Chef's Table", "price": 3500.00, "tier": "vip", "qty": 40},
                ],
            },
            {
                "slug": "toronto-global-founders-angels-summit",
                "title": "Toronto Global Founders & Angels Summit",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "startup-innovation",
                "cover_url": "https://images.unsplash.com/photo-1515187029135-18ee286d815b?w=1200&auto=format&fit=crop&q=80",
                "description": "Canada's top venture capitalists, growth-stage SaaS founders, and angel syndicates gather for curated 1-on-1 deal rooms, pitch stages, and keynote firesides.",
                "format": "in_person",
                "city": "Toronto",
                "country": "CA",
                "venue_name": "Metro Toronto Convention Centre",
                "venue_address": "255 Front St W, Toronto, ON M5V 2W6",
                "tz": "America/Toronto",
                "lat": 43.6435,
                "lng": -79.3871,
                "days_ahead": 19,
                "duration_hours": 8,
                "capacity": 1600,
                "vibe_tags": ["Angel Investors", "SaaS", "Canada Tech"],
                "currency": "CAD",
                "tickets": [
                    {"name": "Founder Admission", "price": 220.00, "tier": "paid", "qty": 900},
                    {"name": "Investor All-Access", "price": 550.00, "tier": "vip", "qty": 250},
                ],
            },
            {
                "slug": "sydney-harbour-wellness-marathon-festival",
                "title": "Sydney Harbour Wellness & Marathon Festival",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "sports-fitness",
                "cover_url": "https://images.unsplash.com/photo-1552674605-db6ffd4facb5?w=1200&auto=format&fit=crop&q=80",
                "description": "Scenic 10K, half-marathon, and sunrise yoga sessions traversing Sydney Harbour Bridge and ending at Circular Quay with recovery cold plunges and wellness workshops.",
                "format": "in_person",
                "city": "Sydney",
                "country": "AU",
                "venue_name": "Overseas Passenger Terminal",
                "venue_address": "130 Argyle St, The Rocks, Sydney NSW 2000",
                "tz": "Australia/Sydney",
                "lat": -33.8568,
                "lng": 151.2093,
                "days_ahead": 22,
                "duration_hours": 6,
                "capacity": 3500,
                "vibe_tags": ["Running", "Wellness", "Harbour View"],
                "currency": "USD",
                "tickets": [
                    {"name": "10K Race & Medal Entry", "price": 55.00, "tier": "paid", "qty": 2000},
                    {"name": "Half Marathon & Recovery Village", "price": 95.00, "tier": "paid", "qty": 1200},
                ],
            },
            {
                "slug": "sao-paulo-jazz-bossa-nova-extravaganza",
                "title": "São Paulo Jazz & Bossa Nova Extravaganza",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "music",
                "cover_url": "https://images.unsplash.com/photo-1511192336575-5a79af67a629?w=1200&auto=format&fit=crop&q=80",
                "description": "Immerse yourself in authentic Brazilian rhythms, Afro-Latin percussion, and classical bossa nova performances beneath the Oscar Niemeyer canopy of Parque Ibirapuera.",
                "format": "in_person",
                "city": "São Paulo",
                "country": "BR",
                "venue_name": "Auditório Ibirapuera",
                "venue_address": "Av. Pedro Álvares Cabral, Moema, São Paulo - SP",
                "tz": "America/Sao_Paulo",
                "lat": -23.5874,
                "lng": -46.6576,
                "days_ahead": 17,
                "duration_hours": 7,
                "capacity": 1800,
                "vibe_tags": ["Bossa Nova", "Live Jazz", "Acoustics"],
                "currency": "USD",
                "tickets": [
                    {"name": "Open Lawn Entry", "price": 25.00, "tier": "paid", "qty": 1200},
                    {"name": "Auditorium Tier 1 Seat", "price": 75.00, "tier": "paid", "qty": 400},
                ],
            },
            {
                "slug": "amsterdam-sustainable-urban-living-expo",
                "title": "Amsterdam Sustainable Urban Living Expo",
                "org_slug": "global-summit-collective",
                "category_slug": "community",
                "cover_url": "https://images.unsplash.com/photo-1497366216548-37526070297c?w=1200&auto=format&fit=crop&q=80",
                "description": "Showcasing circular economy housing, electric water transit, micro-mobility corridors, and urban vertical farms across Europe at RAI Amsterdam.",
                "format": "in_person",
                "city": "Amsterdam",
                "country": "NL",
                "venue_name": "RAI Amsterdam",
                "venue_address": "Europaplein 24, 1078 GZ Amsterdam",
                "tz": "Europe/Amsterdam",
                "lat": 52.3414,
                "lng": 4.8893,
                "days_ahead": 26,
                "duration_hours": 8,
                "capacity": 2500,
                "vibe_tags": ["Circularity", "Smart Cities", "Europe"],
                "currency": "EUR",
                "tickets": [
                    {"name": "General Admission Pass", "price": 45.00, "tier": "paid", "qty": 1800},
                ],
            },
            {
                "slug": "asia-pacific-biotech-health-innovation-congress",
                "title": "Asia-Pacific BioTech & Health Innovation Congress",
                "org_slug": "global-summit-collective",
                "category_slug": "health-wellness",
                "cover_url": "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=1200&auto=format&fit=crop&q=80",
                "description": "Leading genomics researchers, biomedical engineers, and therapeutic venture firms convene at Marina Bay Sands Expo to reveal breakthrough clinical trials.",
                "format": "hybrid",
                "city": "Singapore",
                "country": "SG",
                "venue_name": "Marina Bay Sands Expo and Convention Centre",
                "venue_address": "10 Bayfront Ave, Singapore 018956",
                "tz": "Asia/Singapore",
                "lat": 1.2834,
                "lng": 103.8607,
                "days_ahead": 30,
                "duration_hours": 8,
                "capacity": 2000,
                "vibe_tags": ["BioTech", "Genomics", "Healthcare"],
                "currency": "USD",
                "tickets": [
                    {"name": "Scientific Delegate Ticket", "price": 320.00, "tier": "paid", "qty": 800},
                    {"name": "Virtual Access Streaming Pass", "price": 50.00, "tier": "paid", "qty": 1500},
                ],
            },
            {
                "slug": "dublin-craft-beer-spirits-culinary-fair",
                "title": "Dublin Craft Beer, Spirits & Culinary Fair",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "food-drink",
                "cover_url": "https://images.unsplash.com/photo-1514933651103-005eec06c04b?w=1200&auto=format&fit=crop&q=80",
                "description": "Taste over 150 independent craft stouts, artisanal whiskeys, and Irish farmhouse cheeses accompanied by live folk bands inside the Royal Dublin Society.",
                "format": "in_person",
                "city": "Dublin",
                "country": "IE",
                "venue_name": "Royal Dublin Society (RDS)",
                "venue_address": "Merrion Rd, Ballsbridge, Dublin 4, D04 AK83",
                "tz": "Europe/Dublin",
                "lat": 53.3263,
                "lng": -6.2285,
                "days_ahead": 11,
                "duration_hours": 6,
                "capacity": 3000,
                "vibe_tags": ["Craft Beer", "Culinary", "Live Folk"],
                "currency": "EUR",
                "tickets": [
                    {"name": "Tasting Entry & 5 Drink Tokens", "price": 32.00, "tier": "paid", "qty": 2200},
                    {"name": "Master Distiller Masterclass Pass", "price": 75.00, "tier": "vip", "qty": 200},
                ],
            },
            {
                "slug": "lisbon-web-creators-digital-nomads-conclave",
                "title": "Lisbon Web Creators & Digital Nomads Conclave",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "networking",
                "cover_url": "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=1200&auto=format&fit=crop&q=80",
                "description": "A vibrant gathering for indie hackers, remote product creators, and travel vloggers along the Tagus River at Hub Criativo do Beato in Lisbon.",
                "format": "in_person",
                "city": "Lisbon",
                "country": "PT",
                "venue_name": "Hub Criativo do Beato",
                "venue_address": "R. da Manutenção 118, 1900-321 Lisboa",
                "tz": "Europe/Lisbon",
                "lat": 38.7360,
                "lng": -9.1080,
                "days_ahead": 13,
                "duration_hours": 7,
                "capacity": 1200,
                "vibe_tags": ["Remote Work", "Indie Hackers", "Co-working"],
                "currency": "EUR",
                "tickets": [
                    {"name": "Early Nomad Pass", "price": 40.00, "tier": "paid", "qty": 800},
                ],
            },
            {
                "slug": "johannesburg-international-mining-tech-indaba",
                "title": "Johannesburg International Mining & Tech Indaba",
                "org_slug": "global-summit-collective",
                "category_slug": "business",
                "cover_url": "https://images.unsplash.com/photo-1505373877841-8d25f7d46678?w=1200&auto=format&fit=crop&q=80",
                "description": "Africa's most critical deal-making stage for critical minerals, geological satellite AI, clean beneficiation, and industrial automation in Sandton.",
                "format": "in_person",
                "city": "Johannesburg",
                "country": "ZA",
                "venue_name": "Sandton Convention Centre",
                "venue_address": "161 Maude St, Sandown, Sandton, 2196",
                "tz": "Africa/Johannesburg",
                "lat": -26.1076,
                "lng": 28.0536,
                "days_ahead": 27,
                "duration_hours": 9,
                "capacity": 2800,
                "vibe_tags": ["Mining", "Venture Capital", "Africa Economy"],
                "currency": "ZAR",
                "tickets": [
                    {"name": "Trade Visitor Pass", "price": 850.00, "tier": "paid", "qty": 1800},
                    {"name": "Executive Delegate Pass", "price": 3200.00, "tier": "vip", "qty": 400},
                ],
            },
            {
                "slug": "austin-indie-music-creative-showcase",
                "title": "Austin Indie Music & Creative Showcase",
                "org_slug": "vanguard-creative-labs",
                "category_slug": "music",
                "cover_url": "https://images.unsplash.com/photo-1459749411175-04bf5292ceea?w=1200&auto=format&fit=crop&q=80",
                "description": "Catch 40 groundbreaking independent singer-songwriters, synth-pop duos, and rock bands live at ACL Live at The Moody Theater in downtown Austin.",
                "format": "in_person",
                "city": "Austin",
                "country": "US",
                "venue_name": "Austin City Limits Live",
                "venue_address": "310 W Willie Nelson Blvd, Austin, TX 78701",
                "tz": "America/Chicago",
                "lat": 30.2655,
                "lng": -97.7471,
                "days_ahead": 8,
                "duration_hours": 7,
                "capacity": 2700,
                "vibe_tags": ["Indie Rock", "Live Stage", "Austin"],
                "currency": "USD",
                "tickets": [
                    {"name": "General Admission Floor", "price": 45.00, "tier": "paid", "qty": 1600},
                    {"name": "Mezzanine VIP Seating", "price": 120.00, "tier": "vip", "qty": 300},
                ],
            },
            {
                "slug": "cairo-heritage-arts-ancient-wonders-symposium",
                "title": "Cairo Heritage, Arts & Ancient Wonders Symposium",
                "org_slug": "global-summit-collective",
                "category_slug": "arts-culture",
                "cover_url": "https://images.unsplash.com/photo-1566127444979-b3d2b654e3d7?w=1200&auto=format&fit=crop&q=80",
                "description": "World-renowned Egyptologists, virtual reality museum curators, and cultural preservation architects convene next to the Pyramids at the Grand Egyptian Museum.",
                "format": "hybrid",
                "city": "Cairo",
                "country": "EG",
                "venue_name": "Grand Egyptian Museum Conference Centre",
                "venue_address": "Alexandria Desert Rd, Kafr Nassar, Al Haram, Giza Governorate",
                "tz": "Africa/Cairo",
                "lat": 29.9950,
                "lng": 31.1190,
                "days_ahead": 20,
                "duration_hours": 7,
                "capacity": 1500,
                "vibe_tags": ["Egyptology", "Antiquities", "Museum"],
                "currency": "USD",
                "tickets": [
                    {"name": "Symposium Pass", "price": 85.00, "tier": "paid", "qty": 900},
                    {"name": "Virtual Livestream Pass", "price": 15.00, "tier": "paid", "qty": 3000},
                ],
            },
        ]

        # Insert events
        for ev in events_data:
            existing = await db.scalar(select(Event).where(Event.slug == ev["slug"]))
            if existing:
                print(f"Event {ev['slug']} already exists, skipping.")
                continue

            target_org = host_orgs.get(ev["org_slug"], primary_org)
            event_tz = ZoneInfo(ev["tz"])
            start_date = (now + timedelta(days=ev["days_ahead"])).date()
            start_time = time(10, 0, 0)
            local_start = datetime.combine(start_date, start_time, tzinfo=event_tz)
            local_end = local_start + timedelta(hours=ev["duration_hours"])

            new_ev = Event(
                org_id=target_org.id,
                created_by=admin.id,
                title=ev["title"],
                slug=ev["slug"],
                description=ev["description"],
                cover_image_url=ev["cover_url"],
                og_image_url=ev["cover_url"],
                status="published",
                format=ev["format"],
                start_datetime=local_start.astimezone(timezone.utc),
                end_datetime=local_end.astimezone(timezone.utc),
                timezone=ev["tz"],
                venue_name=ev["venue_name"],
                venue_address=ev["venue_address"],
                venue_city=ev["city"],
                venue_country=ev["country"],
                venue_lat=ev["lat"],
                venue_lng=ev["lng"],
                max_capacity=ev["capacity"],
                is_featured=True,
                pass_fees_to_buyer=True,
                vibe_tags=ev["vibe_tags"],
            )

            # Link category
            cat_obj = cats_by_slug.get(ev["category_slug"])
            if cat_obj:
                new_ev.categories.append(cat_obj)

            db.add(new_ev)
            await db.flush()

            # Add tickets
            for i, tk in enumerate(ev["tickets"], start=1):
                t_obj = TicketType(
                    event_id=new_ev.id,
                    name=tk["name"],
                    price=tk["price"],
                    currency=ev["currency"],
                    tier=tk["tier"],
                    quantity=tk["qty"],
                    is_visible=True,
                    sort_order=i,
                )
                db.add(t_obj)

            print(f"Created event: {new_ev.title} ({ev['city']}, {ev['country']})")

        # 4. Define 10 International Vendors with Complete Profiles
        vendors_data = [
            {
                "email": "contact@luminarystudios.co.uk",
                "name": "Luminary Studios London",
                "slug": "luminary-studios-london",
                "category": "photography",
                "tagline": "Editorial, documentary, and high-profile corporate event photography across Europe.",
                "description": "Luminary Studios is an elite London-based visual agency specializing in commercial conferences, galas, brand activations, and cultural gatherings. Equipped with dual-rig medium format and high-speed mirrorless bodies, our four lead photographers capture decisive moments with stunning color fidelity and unmatched aesthetic refinement.",
                "city": "London",
                "country": "GB",
                "address": "14 Shoreditch High St, Hackney, London E1 6PG",
                "phone": "+44 20 7946 0912",
                "website": "https://luminarystudios.co.uk",
                "cover_url": "https://images.unsplash.com/photo-1537633552985-df8429e8048b?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80",
                "starting_price": 650.00,
                "currency": "GBP",
                "price_range": "premium",
                "rating": 4.9,
                "reviews_count": 34,
                "service_areas": ["Greater London", "Manchester", "Edinburgh", "Paris"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?w=800&auto=format&fit=crop&q=80",
                    "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=800&auto=format&fit=crop&q=80",
                    "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Full-Day Summit Coverage Package",
                        "slug": "full-day-summit-coverage",
                        "price": 1400.00,
                        "currency": "GBP",
                        "inclusions": ["2 Lead Photographers (8 Hours)", "Live On-site Editing & Press Feeds", "Full High-Res Color Graded Gallery", "Commercial Rights"],
                        "duration_hours": 8,
                    },
                    {
                        "title": "Executive Portrait & Gala Session",
                        "slug": "executive-portrait-gala-session",
                        "price": 750.00,
                        "currency": "GBP",
                        "inclusions": ["Mobile Studio Lighting Setup", "Speaker Headshots & VIP Step-and-Repeat", "Same-Day Delivery"],
                        "duration_hours": 4,
                    },
                ],
                "reviews": [
                    {
                        "title": "Outstanding corporate coverage",
                        "rating": 5,
                        "content": "Luminary captured our 2,000-person fintech summit flawlessly. Press photos were delivered within two hours of the opening keynote. Unbelievable professionalism.",
                    },
                    {
                        "title": "World-class aesthetic",
                        "rating": 5,
                        "content": "Their eye for lighting and candid attendee reactions elevated our annual gala. Booking them again next year without hesitation.",
                    },
                ],
            },
            {
                "email": "hello@vanguardeventsnyc.com",
                "name": "Vanguard Events NYC",
                "slug": "vanguard-events-nyc",
                "category": "event_planning",
                "tagline": "Turnkey experiential production, luxury weddings, and bespoke corporate summits in Manhattan.",
                "description": "Vanguard Events NYC brings over twelve years of architectural space transformation, multi-vendor coordination, and high-stakes timeline execution across Tribeca, Midtown, and the Hamptons. We manage everything from permits and technical staging to guest concierge with white-glove precision.",
                "city": "New York",
                "country": "US",
                "address": "450 Lexington Ave, New York, NY 10017",
                "phone": "+1 (212) 555-0198",
                "website": "https://vanguardeventsnyc.com",
                "cover_url": "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&auto=format&fit=crop&q=80",
                "starting_price": 2500.00,
                "currency": "USD",
                "price_range": "premium",
                "rating": 5.0,
                "reviews_count": 48,
                "service_areas": ["Manhattan", "Brooklyn", "The Hamptons", "Westchester"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=800&auto=format&fit=crop&q=80",
                    "https://images.unsplash.com/photo-1511578314322-379afb476865?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Comprehensive Production & Vendor Management",
                        "slug": "comprehensive-production-vendor-mgmt",
                        "price": 5000.00,
                        "currency": "USD",
                        "inclusions": ["Full Vendor RFP & Negotiation", "CAD Floorplans & 3D Renderings", "On-site Day-of Command Staff (4 Members)", "Audio/Visual Coordination"],
                        "duration_hours": 12,
                    },
                    {
                        "title": "Curated Event Styling & Design Direction",
                        "slug": "curated-styling-design-direction",
                        "price": 2800.00,
                        "currency": "USD",
                        "inclusions": ["Concept Mood Boards", "Floral & Scenography Sourcing", "Lighting Design Coordination"],
                        "duration_hours": 6,
                    },
                ],
                "reviews": [
                    {
                        "title": "Flawless Manhattan conference execution",
                        "rating": 5,
                        "content": "Vanguard managed our 3-day conference with 1,500 delegates without a single hitch. Their vendor coordination and calm leadership on-site was pure gold.",
                    },
                ],
            },
            {
                "email": "booking@savannahsound.co.ke",
                "name": "Savannah Sound & Stage Pro",
                "slug": "savannah-sound-stage-ke",
                "category": "sound_lighting",
                "tagline": "Concert-grade line arrays, intelligent stage lighting, and broadcast audio in East Africa.",
                "description": "Savannah Sound & Stage Pro powers the biggest festivals, corporate stadiums, and broadcast events in Kenya and East Africa. Our inventory includes L-Acoustics K2 systems, digital mixing consoles (DiGiCo, Allen & Heath), automated moving-head lighting, and redundant backline generators.",
                "city": "Nairobi",
                "country": "KE",
                "address": "Enterprise Road, Industrial Area, Nairobi",
                "phone": "+254 711 234567",
                "website": "https://savannahsound.co.ke",
                "cover_url": "https://images.unsplash.com/photo-1501386761578-eac5c94b800a?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&auto=format&fit=crop&q=80",
                "starting_price": 85000.00,
                "currency": "KES",
                "price_range": "premium",
                "rating": 4.8,
                "reviews_count": 27,
                "service_areas": ["Nairobi", "Mombasa", "Kisumu", "Kigali"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=800&auto=format&fit=crop&q=80",
                    "https://images.unsplash.com/photo-1516450360452-9312f5e86fc7?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Festival Main Stage Audio & Lighting Rig",
                        "slug": "festival-main-stage-audio-rig",
                        "price": 250000.00,
                        "currency": "KES",
                        "inclusions": ["Dual Line Array Towers", "32 Intelligent Moving Beam Lights", "Front-of-House Audio Engineer & Crew", "Wireless Mic Rack"],
                        "duration_hours": 10,
                    },
                    {
                        "title": "Corporate Conference AV Setup",
                        "slug": "corporate-conference-av-setup",
                        "price": 95000.00,
                        "currency": "KES",
                        "inclusions": ["4 Point Column PA", "Stage Wash Lighting", "6 Lavalier & Handheld Mics", "Live Stream Audio Feed"],
                        "duration_hours": 8,
                    },
                ],
                "reviews": [
                    {
                        "title": "Pristine acoustic clarity",
                        "rating": 5,
                        "content": "Crystal-clear sound across our outdoor amphitheater. The sound engineers handled complex live band transitions smoothly.",
                    },
                ],
            },
            {
                "email": "contact@legourmetparisien.fr",
                "name": "Le Gourmet Parisien Catering",
                "slug": "le-gourmet-parisien-catering",
                "category": "catering",
                "tagline": "Haute cuisine canapés, French gastronomy, and bespoke sommelier wine pairings in Paris.",
                "description": "Headed by alumni of legendary French culinary academies, Le Gourmet Parisien crafts exquisite culinary moments for diplomatic receptions, fashion week galas, and romantic chateau celebrations. All produce is sourced organically from artisan regional farms across Normandy and Provence.",
                "city": "Paris",
                "country": "FR",
                "address": "28 Rue du Faubourg Saint-Honoré, 75008 Paris",
                "phone": "+33 1 42 68 55 00",
                "website": "https://legourmetparisien.fr",
                "cover_url": "https://images.unsplash.com/photo-1555244162-803834f70033?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1577219491135-ce391730fb2c?w=400&auto=format&fit=crop&q=80",
                "starting_price": 950.00,
                "currency": "EUR",
                "price_range": "premium",
                "rating": 4.9,
                "reviews_count": 41,
                "service_areas": ["Paris Île-de-France", "Versailles", "Chantilly"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Cocktail Dînatoire & Champagne Reception (Up to 100 Guests)",
                        "slug": "cocktail-dinatoire-champagne-reception",
                        "price": 2800.00,
                        "currency": "EUR",
                        "inclusions": ["12 Handcrafted Canapé Varieties", "Oyster & Caviar Bar", "Uniformed Service Staff", "Sommelier Selected Champagne Pairing"],
                        "duration_hours": 4,
                    },
                ],
                "reviews": [
                    {
                        "title": "Sublime culinary excellence",
                        "rating": 5,
                        "content": "Our international fashion launch guests were completely enchanted by the canapés and sommelier selections. Flawless French hospitality.",
                    },
                ],
            },
            {
                "email": "cinema@atlanticcape.co.za",
                "name": "Atlantic Cinematics Cape Town",
                "slug": "atlantic-cinematics-cape-town",
                "category": "videography",
                "tagline": "Cinematic 4K event films, drone aerials, and multi-cam live broadcast feeds.",
                "description": "Atlantic Cinematics is an award-winning production collective operating across Cape Town and the Winelands. We produce breathtaking aftermovies, corporate highlight documentaries, and multi-cam broadcast streams using RED Digital Cinema and Sony FX6 camera packages.",
                "city": "Cape Town",
                "country": "ZA",
                "address": "Kloof Street, Gardens, Cape Town, 8001",
                "phone": "+27 21 424 9911",
                "website": "https://atlanticcape.co.za",
                "cover_url": "https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=400&auto=format&fit=crop&q=80",
                "starting_price": 8500.00,
                "currency": "ZAR",
                "price_range": "mid",
                "rating": 4.9,
                "reviews_count": 22,
                "service_areas": ["Cape Town", "Stellenbosch", "Franschhoek"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Full Event Cinematic Aftermovie + Social Cutdowns",
                        "slug": "full-event-cinematic-aftermovie",
                        "price": 18500.00,
                        "currency": "ZAR",
                        "inclusions": ["2 Cinematographers (8 Hours)", "FAA-Licensed 4K FPV Drone Pilot", "3-5 Minute Main Film + 3 Vertical Reels", "Licensed Music Score"],
                        "duration_hours": 8,
                    },
                ],
                "reviews": [
                    {
                        "title": "Felt like a Netflix documentary!",
                        "rating": 5,
                        "content": "The aftermovie of our electronic music showcase captured the spirit, the ocean sunset, and the crowd energy like nothing else.",
                    },
                ],
            },
            {
                "email": "events@opulencedubai.ae",
                "name": "Opulence Luxury Event Decor Dubai",
                "slug": "opulence-event-decor-dubai",
                "category": "decorations",
                "tagline": "Grand floral sculpures, bespoke crystal chandeliers, and lavish ballroom scaping in the UAE.",
                "description": "Opulence Decor transforms premier venues across Dubai, Abu Dhabi, and the Arabian Gulf into breathtaking visual fantasies. From mirrored catwalks and imported Dutch flora to illuminated ceiling canopies and golden archways, our artisans deliver unforgettable grandeur.",
                "city": "Dubai",
                "country": "AE",
                "address": "Al Quoz Industrial Area 3, Dubai",
                "phone": "+971 4 338 8820",
                "website": "https://opulencedubai.ae",
                "cover_url": "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=400&auto=format&fit=crop&q=80",
                "starting_price": 5000.00,
                "currency": "AED",
                "price_range": "premium",
                "rating": 5.0,
                "reviews_count": 39,
                "service_areas": ["Dubai", "Abu Dhabi", "Sharjah", "Ras Al Khaimah"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Royal Ballroom Transformation Package",
                        "slug": "royal-ballroom-transformation",
                        "price": 25000.00,
                        "currency": "AED",
                        "inclusions": ["Grand Floral Ceiling Installations", "Mirrored Custom Tables & Charger Plates", "Ambient LED Architectural Up-lighting", "Full Setup & Midnight Breakdown Crew"],
                        "duration_hours": 12,
                    },
                ],
                "reviews": [
                    {
                        "title": "Pure Arabian grandeur",
                        "rating": 5,
                        "content": "Opulence turned a blank ballroom into an enchanted floral palace. The guests were taking pictures constantly.",
                    },
                ],
            },
            {
                "email": "djblackstar@goldencoast.gh",
                "name": "DJ BlackStar & Golden Coast Sounds",
                "slug": "dj-blackstar-golden-coast",
                "category": "djs",
                "tagline": "Legendary Afrobeats, Highlife, Amapiano, and global party curation in Accra.",
                "description": "Recognized across West Africa, DJ BlackStar brings unmatched dancefloor instincts, seamless transitions, and infectious energy to festivals, corporate brand launches, and destination weddings. Backed by state-of-the-art Pioneer DJ rigs and wireless mic systems.",
                "city": "Accra",
                "country": "GH",
                "address": "Osu Oxford Street, Accra",
                "phone": "+233 24 555 7890",
                "website": "https://djblackstar.com",
                "cover_url": "https://images.unsplash.com/photo-1571266028243-3716f02d2d2e?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=400&auto=format&fit=crop&q=80",
                "starting_price": 2500.00,
                "currency": "GHS",
                "price_range": "mid",
                "rating": 4.9,
                "reviews_count": 52,
                "service_areas": ["Accra", "Kumasi", "Takoradi", "Lagos"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Prime Event DJ Set & Sound Curation (6 Hours)",
                        "slug": "prime-event-dj-set",
                        "price": 5500.00,
                        "currency": "GHS",
                        "inclusions": ["Pioneer CDJ-3000 Setup", "Full Sound & Wireless Mic Kit", "MC Interaction & Custom Playlist Consultation"],
                        "duration_hours": 6,
                    },
                ],
                "reviews": [
                    {
                        "title": "Kept 800 people dancing all night",
                        "rating": 5,
                        "content": "Nobody left the floor until 3 AM. His timing and track selection between Afrobeats and global hits was mastery.",
                    },
                ],
            },
            {
                "email": "studio@northstarbranding.ca",
                "name": "NorthStar Creative & Event Branding",
                "slug": "northstar-creative-branding",
                "category": "branding",
                "tagline": "Large-format print, custom exhibition booths, and attendee merch suites in Toronto.",
                "description": "NorthStar Creative transforms conferences and retail pop-ups into unforgettable branded environments. We handle graphic identity systems, high-durability fabric banners, eco-friendly badge credentials, step-and-repeat walls, and laser-engraved sponsor installations.",
                "city": "Toronto",
                "country": "CA",
                "address": "120 King St W, Toronto, ON M5H 1T9",
                "phone": "+1 (416) 555-8822",
                "website": "https://northstarbranding.ca",
                "cover_url": "https://images.unsplash.com/photo-1542744094-3a31f272c490?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&auto=format&fit=crop&q=80",
                "starting_price": 900.00,
                "currency": "CAD",
                "price_range": "mid",
                "rating": 4.8,
                "reviews_count": 18,
                "service_areas": ["Greater Toronto Area", "Ottawa", "Montreal"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1515187029135-18ee286d815b?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Full Expo Branding & Signage Suite",
                        "slug": "full-expo-branding-suite",
                        "price": 3200.00,
                        "currency": "CAD",
                        "inclusions": ["20ft Tension Fabric Stage Backdrop", "Directional Signage & Wayfinding Totems", "200 Custom Printed Event Lanyards & Passes", "On-site Delivery & Installation"],
                        "duration_hours": 8,
                    },
                ],
                "reviews": [
                    {
                        "title": "Crisp printing and immaculate setup",
                        "rating": 5,
                        "content": "Delivered and installed our summit stage backdrops ahead of schedule. The print quality under stage lighting was flawless.",
                    },
                ],
            },
            {
                "email": "kontakt@kraftwerk-rentals.de",
                "name": "Kraftwerk Stage & Audio Rentals Berlin",
                "slug": "kraftwerk-stage-audio-berlin",
                "category": "equipment_rentals",
                "tagline": "Heavy-duty outdoor staging, hydraulic trussing, and powerhouse generator rentals in Germany.",
                "description": "Kraftwerk Rentals supplies turnkey structural scaffolding, festival stage roofs, crowd control barriers, and German-engineered silenced power generators for European music festivals, sporting arenas, and municipal gatherings.",
                "city": "Berlin",
                "country": "DE",
                "address": "Holzmarktstraße 25, 10243 Berlin",
                "phone": "+49 30 5566 7788",
                "website": "https://kraftwerk-rentals.de",
                "cover_url": "https://images.unsplash.com/photo-1470229722913-7c0e2dbbafd3?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=400&auto=format&fit=crop&q=80",
                "starting_price": 750.00,
                "currency": "EUR",
                "price_range": "premium",
                "rating": 5.0,
                "reviews_count": 29,
                "service_areas": ["Berlin", "Hamburg", "Leipzig", "Cologne"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1516450360452-9312f5e86fc7?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Covered Modular Festival Stage (10x8m)",
                        "slug": "covered-modular-festival-stage",
                        "price": 4200.00,
                        "currency": "EUR",
                        "inclusions": ["Heavy Duty Aluminum Trussing Roof", "Non-slip Stage Decks with Guardrails", "Dual Access Stairways", "TÜV Safety Certified Technicians"],
                        "duration_hours": 24,
                    },
                ],
                "reviews": [
                    {
                        "title": "German engineering at its best",
                        "rating": 5,
                        "content": "Reliable, robust, and safety certified. Withstood torrential summer rain during our outdoor weekend festival without missing a beat.",
                    },
                ],
            },
            {
                "email": "orders@sakura-patisserie.jp",
                "name": "Sakura Artisan Patisserie & Confections",
                "slug": "sakura-artisan-patisserie-tokyo",
                "category": "cakes_desserts",
                "tagline": "Matcha gateaux, sculpted multi-tier celebratory cakes, and Wagashi fusion dessert bars in Tokyo.",
                "description": "Blended with traditional Kyoto matcha, Japanese yuzu, and French confectionery techniques, Sakura Patisserie creates show-stopping dessert installations, bespoke tiers for weddings, and corporate dessert tables across Tokyo and Kanagawa.",
                "city": "Tokyo",
                "country": "JP",
                "address": "5 Chome-7-22 Minamiaoyama, Minato City, Tokyo 107-0062",
                "phone": "+81 3 3400 1234",
                "website": "https://sakurapatisserie.jp",
                "cover_url": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=1200&auto=format&fit=crop&q=80",
                "logo_url": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=400&auto=format&fit=crop&q=80",
                "starting_price": 18000.00,
                "currency": "JPY",
                "price_range": "premium",
                "rating": 4.9,
                "reviews_count": 45,
                "service_areas": ["Tokyo", "Yokohama", "Chiba"],
                "portfolio_urls": [
                    "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=800&auto=format&fit=crop&q=80",
                ],
                "services": [
                    {
                        "title": "Bespoke 3-Tier Ceremonial Cake & Dessert Table",
                        "slug": "bespoke-ceremonial-cake-dessert-table",
                        "price": 75000.00,
                        "currency": "JPY",
                        "inclusions": ["Handcrafted 3-Tier Matcha & White Chocolate Cake", "100 Mini Yuzu Tartlets & Sakura Macarons", "Artisan Table Setup with Fine Ceramic Platters"],
                        "duration_hours": 4,
                    },
                ],
                "reviews": [
                    {
                        "title": "Pure culinary art",
                        "rating": 5,
                        "content": "The cake was both visually breathtaking and delightfully delicate in flavor. The guests couldn't stop taking photographs.",
                    },
                ],
            },
        ]

        # Insert vendors
        for vd in vendors_data:
            existing_v = await db.scalar(select(Vendor).where(Vendor.slug == vd["slug"]))
            if existing_v:
                print(f"Vendor {vd['slug']} already exists, skipping.")
                continue

            v_user = await db.scalar(select(User).where(User.email == vd["email"]))
            if not v_user:
                v_user = User(
                    email=vd["email"],
                    full_name=vd["name"],
                    password_hash=hash_password("VendorWorldPass2026!"),
                    role="vendor",
                    is_verified=True,
                )
                db.add(v_user)
                await db.flush()

            v_obj = Vendor(
                user_id=v_user.id,
                business_name=vd["name"],
                slug=vd["slug"],
                category=vd["category"],
                tagline=vd["tagline"],
                description=vd["description"],
                location_city=vd["city"],
                location_country=vd["country"],
                address=vd["address"],
                contact_email=vd["email"],
                contact_phone=vd["phone"],
                website_url=vd["website"],
                cover_image_url=vd["cover_url"],
                logo_url=vd["logo_url"],
                portfolio_urls=vd["portfolio_urls"],
                service_areas=vd["service_areas"],
                social_links={
                    "instagram": f"https://instagram.com/{vd['slug']}",
                    "website": vd["website"],
                },
                operating_hours={
                    "monday": "09:00 - 18:00",
                    "tuesday": "09:00 - 18:00",
                    "wednesday": "09:00 - 18:00",
                    "thursday": "09:00 - 18:00",
                    "friday": "09:00 - 18:00",
                    "saturday": "10:00 - 16:00",
                },
                starting_price=vd["starting_price"],
                currency=vd["currency"],
                price_range=vd["price_range"],
                status="active",
                is_verified=True,
                verification_status="verified",
                verified_at=datetime.now(timezone.utc) - timedelta(days=60),
                subscription_tier="premium",
                rating_avg=vd["rating"],
                reviews_count=vd["reviews_count"],
                is_featured=True,
            )
            db.add(v_obj)
            await db.flush()

            # Add services
            for s in vd["services"]:
                s_obj = VendorServiceListing(
                    vendor_id=v_obj.id,
                    title=s["title"],
                    slug=s["slug"],
                    category=vd["category"],
                    description=f"Professional {s['title']} offered by {vd['name']}.",
                    pricing_type="starting_at",
                    price=s["price"],
                    currency=s["currency"],
                    inclusions=s["inclusions"],
                    duration_hours=s["duration_hours"],
                    is_active=True,
                )
                db.add(s_obj)

            # Add reviews
            for r in vd["reviews"]:
                r_obj = VendorReview(
                    vendor_id=v_obj.id,
                    reviewer_id=admin.id,
                    rating=r["rating"],
                    title=r["title"],
                    content=r["content"],
                    status="published",
                )
                db.add(r_obj)

            print(f"Created vendor: {v_obj.business_name} ({vd['city']}, {vd['country']})")

        await db.commit()
        print("Successfully seeded 20 international events and 10 complete international vendor profiles!")

if __name__ == "__main__":
    asyncio.run(seed_world_events_and_vendors())
