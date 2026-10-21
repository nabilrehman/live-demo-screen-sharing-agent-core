# Hard Rock Hotels knowledge pack: sources

Fetched 2026-10-21 (read-only, no sign-in, no forms submitted) from the public pages below. The facts in brand.md,
offers.md, new-york.md and orlando.md are summarized in our own words; numbers, dates, hours, fees and prices are as
published that day. Offers, hours and prices change: re-check the source pages and re-stamp this date before a demo
that relies on them.

No bot blocking was hit: plain HTTPS GETs (desktop UA) returned 200 for every hotel.hardrock.com page. Offer lists,
room cards and the booking engines render client-side, so those were read with headless Chrome (Playwright).

| Topic | Source |
|---|---|
| Brand home, hero, Unity teaser | https://hotel.hardrock.com/ |
| Destinations by region, addresses | https://hotel.hardrock.com/destinations.aspx |
| Hotels & resorts, Rock Royalty, REVERB | https://hotel.hardrock.com/hotels-and-resorts.aspx |
| Brand offers (rendered list) | https://hotel.hardrock.com/offers.aspx |
| Unity member rates, participating hotels, terms | https://hotel.hardrock.com/member-rates.aspx |
| Unity overview | https://unity.hardrock.com/ |
| Brand experience (Rock Spa, Body Rock, Rock Om, Rock Shop) | https://hotel.hardrock.com/hard-rock-experience.aspx |
| Sound of Your Stay | https://hotel.hardrock.com/sound-of-your-stay.aspx |
| New York home | https://hotel.hardrock.com/new-york/ |
| New York rooms & suites (rendered cards) | https://hotel.hardrock.com/new-york/rooms-and-suites.aspx , /new-york/rock-star-penthouse-suite.aspx |
| New York offers | https://hotel.hardrock.com/new-york/offers.aspx , /new-york/fall-for-new-york.aspx , /new-york/stay-for-a-cause-room-package.aspx , /new-york/members-only.aspx , /new-york/pinktober.aspx |
| New York dining | https://hotel.hardrock.com/new-york/eat-and-drink.aspx , /new-york/sessions.aspx , /new-york/rt60-rooftop-bar.aspx |
| New York amenities, pets, music | https://hotel.hardrock.com/new-york/amenities.aspx , /new-york/unleashed-pet-friendly.aspx , /new-york/sound-of-your-stay.aspx |
| New York area guide | https://hotel.hardrock.com/new-york/area-guide.aspx |
| New York policies (check-in/out, fees, parking, pets) | https://hotel.hardrock.com/new-york/hotel-policies.aspx |
| New York contact | https://hotel.hardrock.com/new-york/contact.aspx |
| New York booking engine (rooms and rates, no sign-in) | https://reservations.hardrockhotels.com/?Hotel=35650&Chain=13924&arrive=2026-11-07&nights=1&adult=2 (Saturday), &arrive=2026-11-10&nights=1 (Tuesday), &promo=PROFALL&arrive=2026-11-10&nights=2 (Fall for New York) |
| Orlando home, rooms, offers | https://hotel.hardrock.com/orlando/ , /orlando/rooms-and-suites.aspx , /orlando/offers.aspx |
| Orlando dining, amenities, policies, park benefits | https://hotel.hardrock.com/orlando/eat-and-drink.aspx , /orlando/amenities.aspx , /orlando/info-policies.aspx , /orlando/theme-park-benefits.aspx |
| Orlando booking engine (Universal Orlando, no dates) | https://reservations.universalorlando.com/ibe/index.aspx?dt1=UEHRH&hgID=706&hotelID=14842 |

Booking engine URL pattern (New York and most chain hotels):
`https://reservations.hardrockhotels.com/?Hotel=35650&Chain=13924&arrive=YYYY-MM-DD&nights=N&adult=2&promo=CODE`
(promo codes seen: PROFALL = Fall for New York, PKGPINK = Stay for a Cause, UNIBAR = Unity member rate, PKGPET = pet
package; rate=HRHBARRSS = Rock Star Suite). Hotel ids: New York 35650, Malta 95955, Cancun 59391, San Diego 56669.
Hard Rock Hotel Orlando books through Universal Orlando's engine (hotelID=14842, promos TOAST, ROMANCE).

Prices in booking.json marked "published" were read from those engine pages for the dates noted; everything marked
"illustrative" is our estimate for the mockup and must not be quoted as a real rate.
