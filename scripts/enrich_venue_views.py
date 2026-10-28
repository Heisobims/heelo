"""
Enrich all 30 venues in the database with curated, high-resolution views
of the building exterior, interior grand halls, surrounding environment,
outdoor terraces/grounds, and atmospheric evening lighting.
"""

import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.vendor import Vendor

# 5 distinct views for each venue:
# [0] Main building exterior/facade
# [1] Grand interior hall/space
# [2] Surrounding environment/landscape/skyline/waterfront
# [3] Outdoor terrace/grounds/courtyard
# [4] Evening/ambient atmospheric view
VENUE_VIEWS = {
    "royal-glasshouse-atrium-london": [
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "manhattan-skyline-ballroom-nyc": [
        "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1505373877841-8d25f7d46678?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1534430480872-3498386e7856?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
    ],
    "pavillon-des-beaux-arts-paris": [
        "https://images.unsplash.com/photo-1520854221256-17451cc331bf?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "mori-modern-arts-grand-hall-tokyo": [
        "https://images.unsplash.com/photo-1503899036084-c55cdd92da26?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1536098561742-ca998e48cbcc?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
    ],
    "victoria-island-oceanfront-lagos": [
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "palm-jumeirah-crystal-pavilion-dubai": [
        "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1518684079-3c830dcef090?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "kraftwerk-spree-arena-berlin": [
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1509356843151-3e7d96241e11?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "marina-sands-conservatory-singapore": [
        "https://images.unsplash.com/photo-1525625293386-3f8f99389edd?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506973035872-a4ec16b8e8d9?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "rift-valley-summit-grounds-nairobi": [
        "https://images.unsplash.com/photo-1547471080-7cc2caa01a7e?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1516426122078-c23e76319801?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1580618672591-eb180b1a973f?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?w=1400&auto=format&fit=crop&q=85",
    ],
    "atlantic-cape-vineyard-capetown": [
        "https://images.unsplash.com/photo-1580618672591-eb180b1a973f?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "distillery-historic-hall-toronto": [
        "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "sydney-harbour-view-pavilion": [
        "https://images.unsplash.com/photo-1506973035872-a4ec16b8e8d9?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1528728329032-2972f65dfb3f?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
    ],
    "keizersgracht-heritage-warehouse-amsterdam": [
        "https://images.unsplash.com/photo-1512470876302-972faa2aa9a4?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1534351590666-13e3e96b5017?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "alpine-summit-hall-zurich": [
        "https://images.unsplash.com/photo-1530122037265-a5f1f91d3b99?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "jardins-modernist-pavilions-saopaulo": [
        "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "labadi-beach-horizon-arena-accra": [
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "kigali-heights-rotunda": [
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "gangnam-tech-innovation-dome-seoul": [
        "https://images.unsplash.com/photo-1538485399081-7191377e8241?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1505373877841-8d25f7d46678?w=1400&auto=format&fit=crop&q=85",
    ],
    "palazzo-dei-fiori-roma": [
        "https://images.unsplash.com/photo-1552832230-c0197dd311b5?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1520854221256-17451cc331bf?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "placa-reial-mediterranean-barcelona": [
        "https://images.unsplash.com/photo-1583422409516-2895a77efded?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "michigan-lakefront-loft-chicago": [
        "https://images.unsplash.com/photo-1494526585095-c41746248156?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "presidio-golden-gate-hangar-sf": [
        "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "pacific-coastal-timber-vancouver": [
        "https://images.unsplash.com/photo-1559511260-66a65e0982d5?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "nordic-waterfront-congress-stockholm": [
        "https://images.unsplash.com/photo-1509356843151-3e7d96241e11?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1512470876302-972faa2aa9a4?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "hofburg-imperial-ballroom-vienna": [
        "https://images.unsplash.com/photo-1516550893923-42d28e5677af?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1520854221256-17451cc331bf?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
    ],
    "silicon-docks-studio-dublin": [
        "https://images.unsplash.com/photo-1549918864-48ac978761a4?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "bandra-sea-link-hub-mumbai": [
        "https://images.unsplash.com/photo-1567157577867-05ccb1388e66?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511795409834-ef04bbd61622?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "polanco-hacienda-courtyard-mexicocity": [
        "https://images.unsplash.com/photo-1518780664697-55e3ad937233?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1519167758481-83f550bb49b3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "old-town-castle-vaults-edinburgh": [
        "https://images.unsplash.com/photo-1506377247377-2a5b3b417ebb?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1464366400600-7168b8af9bc3?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1400&auto=format&fit=crop&q=85",
    ],
    "sunset-hills-villa-losangeles": [
        "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1511578314322-379afb476865?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1534430480872-3498386e7856?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=1400&auto=format&fit=crop&q=85",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1400&auto=format&fit=crop&q=85",
    ],
}

async def enrich():
    async with AsyncSessionLocal() as db:
        print("Enriching venues with multiple building and environment views...")
        updated = 0
        for slug, views in VENUE_VIEWS.items():
            venue = await db.scalar(select(Vendor).where(Vendor.slug == slug))
            if venue:
                venue.cover_image_url = views[0]
                venue.portfolio_urls = views[1:]
                updated += 1
                print(f"Updated views for {venue.business_name} ({len(views)} total views)")
        await db.commit()
        print(f"Successfully enriched {updated} venues with multi-view building and environment galleries!")

if __name__ == "__main__":
    asyncio.run(enrich())

