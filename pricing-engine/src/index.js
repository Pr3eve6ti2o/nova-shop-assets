/**
 * Nova Shop Payment & Pricing Engine — facade.
 *
 * Pipeline (the owner's architecture):
 *   Product Pricing -> Quantity Calculations -> Discount Engine ->
 *   Shipping Fees -> Tax Calculations -> Platform/Gateway Fees -> Total
 *
 * Fiat math is Dinero.js (integer cents); crypto conversion is Decimal.js.
 * The Python bot remains the server-side authority — this engine mirrors
 * its arithmetic cent-for-cent under the parity contract in fiat.js, and
 * shared test vectors (test-vectors.json) are executed against BOTH this
 * engine and the bot's real totals() in bot/tests/test_pricing_parity.py.
 */
import {
  USD,
  subtotalCents,
  percentFloorCents,
  percentHalfUpCents,
  grossUpCents,
  formatMoney,
} from './fiat.js';
import {
  usdCentsToBaseUnits,
  usdCentsToTonNano,
  formatBaseUnits,
} from './crypto-assets.js';

export * from './fiat.js';
export * from './crypto-assets.js';

/**
 * Price an order. All inputs/outputs are integer cents.
 *
 * @param {object} input
 * @param {Array<{priceCents:number, qty:number, categoryId?:number}>} input.items
 * @param {?{kind:'percent'|'fixed', value:number, categoryId?:number}} input.promo
 *        Mirrors the bot's promos table: percent value is 1..100 (floor),
 *        fixed value is cents; a categoryId scopes the discount basis to
 *        that category's subtotal, exactly like db.validate_promo.
 * @param {number} [input.deliveryFeeCents=0]  flat shipping fee (bot: config.DELIVERY_FEE_CENTS)
 * @param {number} [input.taxRatePct=0]        tax on (subtotal - discount), half-up policy
 * @param {?{feePct:number}} [input.gatewayFee] e.g. CryptoBot { feePct: 3 } — gross-up
 * @param {object} [input.currency=USD]
 * @returns {{subtotal:number, discountBasis:number, discount:number,
 *            deliveryFee:number, tax:number, total:number,
 *            gatewayFee:?number, grossTotal:?number}} all integer cents;
 *            total is what the customer owes before any gateway gross-up;
 *            grossTotal (when a gateway is given) is the invoice amount.
 */
export function priceOrder(input) {
  const {
    items,
    promo = null,
    deliveryFeeCents = 0,
    taxRatePct = 0,
    gatewayFee = null,
    currency = USD,
  } = input ?? {};
  if (!Array.isArray(items)) throw new TypeError('items must be an array');

  const subtotal = subtotalCents(items, currency);

  // Discount engine — bot parity (see fiat.js header).
  let discountBasis = subtotal;
  let discount = 0;
  if (promo) {
    if (promo.categoryId != null) {
      discountBasis = subtotalCents(
        items.filter((i) => i.categoryId === promo.categoryId),
        currency,
      );
    }
    if (promo.kind === 'percent') {
      discount = percentFloorCents(discountBasis, promo.value, currency);
    } else if (promo.kind === 'fixed') {
      if (!Number.isSafeInteger(promo.value) || promo.value <= 0) {
        throw new RangeError(`fixed promo value must be positive cents, got ${promo.value}`);
      }
      discount = promo.value;
    } else {
      throw new RangeError(`unknown promo kind: ${promo.kind}`);
    }
    discount = Math.min(discount, discountBasis);
  }
  discount = Math.min(discount, subtotal);

  const deliveryFee = deliveryFeeCents;
  const taxableBase = Math.max(0, subtotal - discount);
  const tax = taxRatePct > 0 ? percentHalfUpCents(taxableBase, taxRatePct, currency) : 0;

  const total = Math.max(0, subtotal - discount + deliveryFee + tax);

  let gatewayFeeCents = null;
  let grossTotal = null;
  if (gatewayFee) {
    const gross = grossUpCents(total, gatewayFee.feePct, currency);
    grossTotal = gross.grossCents;
    gatewayFeeCents = gross.feeCents;
  }

  return {
    subtotal,
    discountBasis,
    discount,
    deliveryFee,
    tax,
    total,
    gatewayFee: gatewayFeeCents,
    grossTotal,
  };
}

/** Everything the Mini App needs, in one namespace-friendly object. */
export const NovaPricing = {
  priceOrder,
  formatMoney,
  usdCentsToBaseUnits,
  usdCentsToTonNano,
  formatBaseUnits,
};
export default NovaPricing;
