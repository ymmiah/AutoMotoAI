---
name: travel-booking
description: Research hotels and trips on Booking.com and similar sites - compare options and give links. Never books or pays.
category: research
tools: web_search, fetch_url
status: live
---
# Travel research (Booking.com and others)

Booking.com's official API is for approved partners only, and booking/paying is always done by the user.
1. Clarify dates, guests, area, budget, must-haves (breakfast, free cancellation, parking).
2. `web_search` e.g. `booking.com hotels near Birmingham New Street free cancellation`; also check the hotel's own site.
3. `fetch_url` the most relevant pages. Prices on search pages change by date and are often hidden from automated
   reads - say when a price couldn't be confirmed and give the search link instead.
4. Compare: name, area/distance, price per night (and total), rating + review count, cancellation policy, link.
5. Hand over links; the user books. Never enter card details or personal data anywhere.
