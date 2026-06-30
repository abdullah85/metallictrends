# API Research — Metal Price Data Sources

## [Metals.dev](https://www.metals.dev/docs)

- **Free plan** — 100 requests/month
- **Commercial plans**
  - $1.79/month (2k requests)
  - $9.99/month (10k requests)
  - $99/month (500k requests)
- **Commercial use of free plan** — not explicitly prohibited; confirmed via email. See [Terms](https://www.metals.dev/policy/terms).

## [MetalpriceAPI](https://metalpriceapi.com)

- **GitHub** — [metalpriceapi/metalpriceapi-python](https://github.com/metalpriceapi/metalpriceapi-python)
- **Free plan** — 100 requests/month. Per [Terms](https://metalpriceapi.com/terms): free tier data is for personal exploration and evaluation only — not for commercial use.
- **Pricing** (see [pricing page](https://metalpriceapi.com/pricing))
  - $5/month billed yearly — $60/year (1k requests/month) *(most favourable)*
  - $12/month billed yearly — $72/year
  - $20–$25/month — $240/year
- **Sponsorship** — [metalpriceapi.com/sponsorship](https://metalpriceapi.com/sponsorship)
- **Commercial use** — subscribers may display data on commercial projects while the subscription is active. Data must not be used commercially after cancellation.

## [GoldAPI](https://www.goldapi.io/)

- **GitHub** — [goldapi-io/gold-api-examples-python](https://github.com/goldapi-io/gold-api-examples-python)
- **Free plan** — 100 requests/month
- **Paid plan** — $99/month. See [Terms of Service](https://www.goldapi.io/blog/terms-of-service).
- **Commercial use** — permitted provided:
  - End users use the data strictly for their own personal or commercial use.
  - End users are not permitted to store, distribute, or exploit the data for other purposes.
- **License for free data** — not explicitly restricted per the above terms.

## [GoldPriceZ](https://goldpricez.com/)

- **Free access** — no hidden charges; registration required (email + site name/URL).
- **API** — REST, returns JSON. See [API docs](https://goldpricez.com/about/api) and [register for a key](https://goldpricez.com/key/registration).
  - **Supported metals** — gold and silver (copper, oil on roadmap).
  - **Endpoints** — `GET /api/rates/currency/{CURRENCY}/measure/{UNIT}` (gold only) and `/metal/all` variant for gold + silver.
  - **Authentication** — API key via `X-API-KEY` header; must be kept server-side and never exposed in client code.
  - **Rate limits** — 30–60 requests/hour (≈ 44,640/month); no SLA, provided as-is.
- **Commercial use** — **not permitted** on the free tier. Reselling, republishing, redistributing, or bulk-storing API data is prohibited. Contact [goldpricekg@gmail.com](mailto:goldpricekg@gmail.com) to enquire about a commercial licence.
- **Attribution** — required when publicly displaying API data (e.g. "Source: GoldPriceZ.com").
- **Terms of Service** — [goldpricez.com/tos](https://goldpricez.com/tos) (updated December 2025, effective January 2026).

## [Metals-API](https://metals-api.com/)

- No free tier — minimum $199/year.