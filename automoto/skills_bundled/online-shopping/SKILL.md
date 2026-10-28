---
name: online-shopping
description: Research products on Amazon, eBay and Etsy - compare prices, specs and reviews - and hand the user links. Never buys anything.
category: research
tools: web_search, fetch_url
status: unit
---
# Online shopping research (Amazon, eBay, Etsy)

AutoMoto **never** buys, bids, adds to basket or messages sellers - the user does that.
Their official APIs (Amazon Product Advertising API, eBay Browse API, Etsy Open API) need partner/developer accounts,
so research uses public pages.
1. `web_search` with the product + site, e.g. `"sony wh-1000xm5" site:amazon.co.uk`, `site:ebay.co.uk`, `site:etsy.com`.
2. `fetch_url` 2-4 product pages; extract price, seller, condition (new/used), delivery cost, returns, rating count.
   Pages may block automated reads or show different prices when signed in - say so.
3. Compare in a table (item, store, price incl. delivery, condition, rating, link). Flag listings that look like scams
   (price far below others, new seller with no feedback, off-platform payment requests).
4. Finish with the links for the user to buy themselves.
