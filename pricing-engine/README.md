# Payment & Pricing Engine

The shop's money-calculation layer, built on the two libraries the project
owner specified:

- **[Dinero.js](https://github.com/dinerojs/dinero.js)** (v2.0.2) — all fiat
  money: product pricing, quantities, discounts, tax, shipping, platform
  and gateway fees. Used per the official
  [dinerojs/skills](https://github.com/dinerojs/skills) best practices:
  integer minor units only, immutable operations, scaled amounts for
  percentages, `allocate` for splits so no cent is lost.
- **[Decimal.js](https://github.com/MikeMcl/decimal.js)** (^10.6.0) — all
  cryptocurrency conversion math: exchange-rate quotes are decimal
  strings and are converted exactly, never through binary floats.
  Resulting amounts are modelled as Dinero objects on the **bigint**
  calculator with custom high-exponent currencies (skill rule
  *precision-crypto*).

## Where it sits

```
Telegram Shop Bot (Python, server-side authority)
        |
Telegram Mini App  ---- uses the browser build of this engine
        |
   Pricing Engine (this package)
        +-- Money Calculations   (Dinero.js, src/fiat.js)
        +-- Product Pricing        (priceOrder, src/index.js)
        +-- Quantity Calculations  (line totals / subtotal)
        +-- Discount Engine        (percent floor / fixed, category-scoped)
        +-- Tax Calculations       (half-up policy, on the discounted base)
        +-- Shipping Fees          (flat delivery fee input)
        +-- Platform Fees          (splitCents via allocate)
        +-- Payment Gateway Fees   (CryptoBot gross-up, bot-identical)
        +-- Currency Conversion    (src/crypto-assets.js)
        +-- Cryptocurrency Amounts (Decimal.js + Dinero bigint)
        |
Order & Payment Database (bot) -> Payment Provider -> Verification
```

## The parity contract (read before changing any formula)

The **Python bot is the server-side authority**: it recomputes every
total from the database and never trusts client amounts. This engine
mirrors the bot's arithmetic *cent-for-cent*:

| Rule | Bot (authority) | Engine |
|---|---|---|
| Subtotal | `sum(price_cents * qty)` | `subtotalCents` |
| Percent promo | `floor(basis * pct / 100)` | `percentFloorCents` (scaled multiply + `transformScale` down) |
| Fixed promo | value cents, clamped to basis | `priceOrder` |
| Discount clamp | `min(discount, subtotal)` | `priceOrder` |
| Total | `max(0, subtotal - discount + delivery_fee)` | `priceOrder` |
| CryptoBot fee | gross = `ceil(net*100/(100-fee_pct))` | `grossUpCents` |
| Crypto quote | `ceil(usd_cents * 10^dec / ceil(price*100))`, Decimal, ROUND_CEILING | `usdCentsToBaseUnits`, Decimal.js, ROUND_CEIL |

Two deliberate engine-only extensions (the bot has no equivalent today;
both default to off, so parity is unaffected):

- **Tax** — `taxRatePct` on the discounted base, rounded **half-up**
  (standard tax practice), fractional rates supported via scaled amounts.
- **Fee splits** — `splitCents` uses Dinero `allocate`, distributing the
  remainder so parts always sum to the whole.

`test-vectors.json` is the shared contract: it runs against this engine
(`test/vectors.test.js`) **and** against the bot's real `totals()`
(`bot/tests/test_pricing_parity.py`). If you change a money rule, change
it in both implementations and extend the vectors.

Crypto asset keys mirror `bot/crypto_payments.py` CHAINS exactly — the
keys are *networks*: on `eth`/`trx` the deposit asset is USDT (6 dp);
`btc` is 8 dp, `ton` is 9 dp (nanotons).

## Usage

```js
import { priceOrder, usdCentsToTonNano, formatMoney } from '@nova-shop/pricing-engine';

const priced = priceOrder({
  items: [{ priceCents: 2999, qty: 1 }, { priceCents: 499, qty: 2 }],
  promo: { kind: 'percent', value: 10 },          // or { kind: 'fixed', value: 500 }
  deliveryFeeCents: 499,
  gatewayFee: { feePct: 3 },                       // CryptoBot gross-up
});
// -> { subtotal: 3997, discountBasis: 3997, discount: 399,
//      deliveryFee: 499, tax: 0, total: 4097,
//      gatewayFee: 127, grossTotal: 4224 }

formatMoney(priced.total);                          // '$40.97'
usdCentsToTonNano(1000, '5.20');                    // '1923076924'
```

## Develop

```bash
cd pricing-engine
npm install
npm test                 # node:test — fiat, crypto, shared vectors
npm run build:browser    # -> miniapp/vendor/pricing-engine.js (IIFE)
python3 ../tools/build_miniapp_bundle.py   # inlines it into miniapp/dist/
```

Requires Node >= 20. The browser bundle exposes `window.NovaPricing`;
`miniapp/app.js` uses it for the cart subtotal and the TON Connect
nanoton conversion, and falls back to its built-in integer math when the
engine is absent, so a stale bundle can never break the storefront.
