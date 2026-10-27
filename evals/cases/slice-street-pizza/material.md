Call summary – Slice Street Pizza x Adyen discovery call, Oct 27
Attendees: Slice Street Head of Digital Payments, Slice Street Store Operations Lead (France), Slice Street IT Architect; Adyen IM, Adyen Account Manager.
Duration: 48 min

Answers to the scoping questions

Track: US
ID-0083: Project Background – Slice Street US runs online ordering through its own website and apps, processing today with a legacy US acquirer. Franchisees own the stores; the central team owns online payments. They want one provider for the US webshop and apps.
ID-0084: Project Goals & Objectives – Go live before the Super Bowl promo window (early February). Reduce declines, migrate stored cards, simplify reconciliation across franchisees.
ID-0001: What regions are in scope? – United States only for the online track.
ID-0002: What Payment Methods are in scope? – Visa, Mastercard, Amex, Discover, Apple Pay, Google Pay, PayPal. Venmo maybe later.
ID-0003: What Payment Currencies are in scope? – USD.
ID-0004: What Settlement Currencies are in scope? – USD.
ID-0077: Where do you need to reuse a shopper's payment credentials? – One-click checkout for logged-in customers (card on file). No subscriptions.
ID-0082: What are the project focus areas? – Fast go-live, token migration, fewer declines, reporting per franchisee.
ID-0098: Which core systems feed the checkout? – Own order management system and a CRM. No ERP in the checkout path.
ID-0132: Is there a procedure to perform payouts? – Not discussed.
ID-0137: Which websites are going to collect payments? – slicestreet.example, the iOS app and the Android app. Two API credentials were mentioned: one for web, one for apps.
ID-0005: User Platforms – iOS, Android, Web.
ID-0018: Payout Model – Not discussed.
ID-0036: Plugin – No plugin; custom checkout on their own stack.
ID-0138: Multiple URLs needing several API credentials? – Yes, web and apps separately.

Track: FR
ID-0001: What regions are in scope? – France, stores only. Around 400 stores, mostly franchise.
ID-0002: What Payment Methods are in scope? – Cartes Bancaires, Visa, Mastercard, Apple Pay on the terminal. Meal vouchers (Edenred) came up, undecided.
ID-0003: What Payment Currencies are in scope? – EUR.
ID-0004: What Settlement Currencies are in scope? – EUR.
ID-0063: Wide range of terminals or mostly countertop? – Mostly countertop at the counter, plus portable terminals for delivery drivers at the door.
ID-0065: Native Terminal API or POS provider? – Their POS vendor has a prebuilt Adyen integration; they want to use it.
ID-0067: Known limitations on the POS side? – Vendor said tipping and partial refunds need a newer POS version; upgrade planned.
ID-0071: Payments only, or other terminal interactions? – Payments only for v1.
ID-0073: Shopper journeys? – Pay at counter, pay at the door on delivery, order online and pay in store on pickup.
ID-0077: Reuse of payment credentials? – Not applicable in store.
ID-0082: Focus areas? – Terminal rollout to 400 stores in two waves, offline capability for delivery drivers.
ID-0098: Core systems feeding the checkout? – The POS vendor's system. Not discussed further.
ID-0132: Payout procedure? – Franchisees are paid out directly today by the current provider; they want the same. Details not discussed.
ID-0137: Websites collecting payments? – Not applicable for the France track.
ID-0006: Terminal Form Factor – Countertop and Portable.
ID-0018: Payout Model – Per franchisee, to be confirmed.
ID-0036: Plugin – POS vendor integration, not an ecommerce plugin.
ID-0138: Multiple URLs needing several API credentials? – Not discussed.
ID-0139: Card readers in scope? If so, iOS or Android? – Not in scope.

Other notes from the call
- Online, they currently store about 6 million card tokens with the legacy acquirer and expect to migrate them; they asked whether network transaction IDs are needed for the migration.
- The architect asked about 3DS in the US: they only want to challenge when the issuer requires it.
- In France, drivers are often out of Wi-Fi range; the ops lead asked whether portable terminals can take payments offline and sync later.
- They want a daily settlement report per franchisee in both countries, and asked whether reconciliation can be split by store.
- Loyalty: they are launching a points program next year and asked if payments can recognise a returning customer in store by card.
- The IT architect asked about surcharging in the US for Amex. Not decided.
- Next steps: Adyen to send the terminal model options for France; Slice Street to confirm the POS version upgrade date.
