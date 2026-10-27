"""
Seed development database with sample published events and organization.
Ensures the chatbot and event discovery pages have realistic, live database records.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, UTC
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.event import Event
from app.models.ticketing import TicketType

async def seed_events():
    async with AsyncSessionLocal() as db:
        # 1. Fetch admin user
        admin = await db.scalar(select(User).where(User.email == "admin@tixdoo.com"))
        if not admin:
            print("Admin user admin@tixdoo.com not found. Please create it first.")
            return

        # 2. Create or fetch organization
        org = await db.scalar(select(Organization).where(Organization.slug == "tixdoo-entertainment"))
        if not org:
            org = Organization(
                owner_id=admin.id,
                name="Tixdoo Entertainment",
                slug="tixdoo-entertainment",
                description="Official event organization showcasing technology, music, and creator experiences.",
                brand_color="#E85938",
                country="NG",
                currency="NGN",
                plan="pro",
                is_active=True,
            )
            db.add(org)
            await db.flush()
            print(f"Created organization: {org.name} ({org.slug})")

            # Add admin as organization member
            member = OrganizationMember(
                org_id=org.id,
                user_id=admin.id,
                invited_email=admin.email,
                role="admin",
                invited_at=datetime.now(UTC),
                accepted_at=datetime.now(UTC),
                status="active",
            )
            db.add(member)
            await db.flush()

        tz_lagos = ZoneInfo("Africa/Lagos")
        now_lagos = datetime.now(tz_lagos)

        # 3. Event 1: This Weekend (Sunday Oct 25, 2026) in Lagos
        ev1 = await db.scalar(select(Event).where(Event.slug == "lagos-tech-creators-summit-2026"))
        if not ev1:
            # Scheduled for today (Sunday Oct 25, 2026 from 14:00 to 20:00 WAT)
            event_date = now_lagos.date()
            start_dt = datetime.combine(event_date, time(14, 0, 0), tzinfo=tz_lagos)
            end_dt = datetime.combine(event_date, time(20, 0, 0), tzinfo=tz_lagos)

            ev1 = Event(
                org_id=org.id,
                created_by=admin.id,
                title="Lagos Tech & Creators Summit 2026",
                slug="lagos-tech-creators-summit-2026",
                description="The premier gathering of Nigerian tech founders, creative innovators, and digital artists.",
                status="published",
                format="in_person",
                start_datetime=start_dt.astimezone(UTC),
                end_datetime=end_dt.astimezone(UTC),
                timezone="Africa/Lagos",
                venue_name="Landmark Centre",
                venue_address="Water Corporation Drive, Oniru, Victoria Island",
                venue_city="Lagos",
                venue_country="NG",
                venue_lat=6.4253,
                venue_lng=3.4441,
                max_capacity=500,
                is_featured=True,
                pass_fees_to_buyer=True,
            )
            db.add(ev1)
            await db.flush()

            t1 = TicketType(
                event_id=ev1.id,
                name="Early Bird Pass",
                price=0,
                currency="NGN",
                tier="free",
                quantity=100,
                is_visible=True,
                sort_order=1,
            )
            t2 = TicketType(
                event_id=ev1.id,
                name="Standard Delegate Pass",
                price=5000,
                currency="NGN",
                tier="general",
                quantity=300,
                is_visible=True,
                sort_order=2,
            )
            t3 = TicketType(
                event_id=ev1.id,
                name="VIP All-Access Pass",
                price=25000,
                currency="NGN",
                tier="vip",
                quantity=100,
                is_visible=True,
                sort_order=3,
            )
            db.add_all([t1, t2, t3])
            print(f"Created event: {ev1.title} ({ev1.slug})")

        # 4. Event 2: Next Weekend (Saturday Oct 31, 2026) in Lagos
        ev2 = await db.scalar(select(Event).where(Event.slug == "afrobeats-live-sound-showcase"))
        if not ev2:
            next_sat = now_lagos.date() + timedelta(days=(5 - now_lagos.weekday() + 7 if now_lagos.weekday() >= 5 else 5 - now_lagos.weekday() + 7))
            start_dt2 = datetime.combine(next_sat, time(18, 0, 0), tzinfo=tz_lagos)
            end_dt2 = datetime.combine(next_sat, time(23, 30, 0), tzinfo=tz_lagos)

            ev2 = Event(
                org_id=org.id,
                created_by=admin.id,
                title="Afrobeats & Live Sound Showcase",
                slug="afrobeats-live-sound-showcase",
                description="An electrifying night of live Afrobeats, fusion jazz, and emerging Nigerian musical talent.",
                status="published",
                format="in_person",
                start_datetime=start_dt2.astimezone(UTC),
                end_datetime=end_dt2.astimezone(UTC),
                timezone="Africa/Lagos",
                venue_name="Eko Atlantic City",
                venue_address="Ahmadu Bello Way, Victoria Island",
                venue_city="Lagos",
                venue_country="NG",
                max_capacity=1000,
                is_featured=True,
                pass_fees_to_buyer=True,
            )
            db.add(ev2)
            await db.flush()

            t2_1 = TicketType(
                event_id=ev2.id,
                name="General Admission",
                price=7500,
                currency="NGN",
                tier="general",
                quantity=800,
                is_visible=True,
                sort_order=1,
            )
            t2_2 = TicketType(
                event_id=ev2.id,
                name="VIP Lounge Access",
                price=35000,
                currency="NGN",
                tier="vip",
                quantity=200,
                is_visible=True,
                sort_order=2,
            )
            db.add_all([t2_1, t2_2])
            print(f"Created event: {ev2.title} ({ev2.slug})")

        # 5. Event 3: Upcoming Virtual Event (Nov 7, 2026)
        ev3 = await db.scalar(select(Event).where(Event.slug == "global-ai-product-strategy-masterclass"))
        if not ev3:
            v_date = now_lagos.date() + timedelta(days=13)
            start_dt3 = datetime.combine(v_date, time(16, 0, 0), tzinfo=UTC)
            end_dt3 = datetime.combine(v_date, time(19, 0, 0), tzinfo=UTC)

            ev3 = Event(
                org_id=org.id,
                created_by=admin.id,
                title="Global AI & Product Strategy Masterclass",
                slug="global-ai-product-strategy-masterclass",
                description="Interactive virtual workshop on designing AI-native platforms and event automation.",
                status="published",
                format="virtual",
                start_datetime=start_dt3,
                end_datetime=end_dt3,
                timezone="UTC",
                virtual_url="https://meet.google.com/abc-defg-hij",
                virtual_platform="google_meet",
                max_capacity=500,
                is_featured=False,
                pass_fees_to_buyer=True,
            )
            db.add(ev3)
            await db.flush()

            t3_1 = TicketType(
                event_id=ev3.id,
                name="Free Virtual Pass",
                price=0,
                currency="USD",
                tier="free",
                quantity=500,
                is_visible=True,
                sort_order=1,
            )
            db.add(t3_1)
            print(f"Created event: {ev3.title} ({ev3.slug})")

        # 6. Seed Sample Verified Vendors
        from app.models.vendor import Vendor
        from app.utils.auth import hash_password

        vendor_data = [
            {
                "email": "apex.visuals@tixdoo.com",
                "name": "Apex Visuals Photography",
                "slug": "apex-visuals-photography",
                "category": "photography",
                "tagline": "Award-winning event, concert, and portrait photography in Lagos.",
                "price": 120000,
                "range": "mid",
                "city": "Lagos",
            },
            {
                "email": "soundwave.dj@tixdoo.com",
                "name": "SoundWave DJ & Stage Audio",
                "slug": "soundwave-dj-audio",
                "category": "dj",
                "tagline": "High-energy sound engineering, club audio, and DJ sets for festivals.",
                "price": 85000,
                "range": "budget",
                "city": "Lagos",
            },
            {
                "email": "royal.feast@tixdoo.com",
                "name": "Royal Feast Catering & Drinks",
                "slug": "royal-feast-catering",
                "category": "catering",
                "tagline": "Gourmet catering, bespoke mocktails, and live food stations.",
                "price": 200000,
                "range": "premium",
                "city": "Lagos",
            },
        ]

        for vd in vendor_data:
            existing_v = await db.scalar(select(Vendor).where(Vendor.slug == vd["slug"]))
            if not existing_v:
                v_user = await db.scalar(select(User).where(User.email == vd["email"]))
                if not v_user:
                    v_user = User(
                        email=vd["email"],
                        full_name=vd["name"],
                        password_hash=hash_password("VendorPass123!"),
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
                    description=vd["tagline"],
                    location_city=vd["city"],
                    location_country="NG",
                    starting_price=vd["price"],
                    currency="NGN",
                    price_range=vd["range"],
                    status="active",
                    is_verified=True,
                    verification_status="verified",
                )
                db.add(v_obj)
                print(f"Created vendor: {v_obj.business_name} ({v_obj.category})")

        # 7. Seed Sample Order and Registration for Admin
        from app.models.ticketing import Order, Registration
        existing_order = await db.scalar(select(Order).where(Order.payment_reference == "HL-DEMO-88219"))
        if not existing_order and ev1:
            order = Order(
                event_id=ev1.id,
                user_id=admin.id,
                buyer_name=admin.full_name or "Admin User",
                buyer_email=admin.email,
                total_amount=0,
                net_amount=0,
                currency="NGN",
                payment_provider="free",
                payment_reference="HL-DEMO-88219",
                payment_status="paid",
            )
            db.add(order)
            await db.flush()

            first_ticket = await db.scalar(select(TicketType).where(TicketType.event_id == ev1.id))
            if first_ticket:
                reg = Registration(
                    event_id=ev1.id,
                    ticket_type_id=first_ticket.id,
                    order_id=order.id,
                    user_id=admin.id,
                    attendee_name=admin.full_name or "Admin User",
                    attendee_email=admin.email,
                    qr_code="QR-SIGNED-DEMO-88219",
                    status="confirmed",
                )
                db.add(reg)
                print(f"Created sample registration for {admin.email} (HL-DEMO-88219)")

        await db.commit()
        print("Database successfully seeded with realistic events, vendors, and orders!")

if __name__ == "__main__":
    asyncio.run(seed_events())

