import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  money,
  centsOf,
  lineTotalCents,
  subtotalCents,
  percentFloorCents,
  percentHalfUpCents,
  grossUpCents,
  splitCents,
  formatMoney,
  priceOrder,
} from '../src/index.js';

test('money only accepts integer cents (dinero creation-minor-units)', () => {
  assert.equal(centsOf(money(1999)), 1999);
  assert.throws(() => money(19.99), TypeError);
  assert.throws(() => money('1999'), TypeError);
});

test('line totals and subtotal are exact integer math', () => {
  assert.equal(lineTotalCents(333, 3), 999);
  assert.equal(
    subtotalCents([{ priceCents: 2999, qty: 1 }, { priceCents: 499, qty: 2 }]),
    3997,
  );
  assert.equal(subtotalCents([]), 0);
});

test('percent floor matches the bot promo rule (basis * pct // 100)', () => {
  assert.equal(percentFloorCents(999, 10), 99);   // 99.9 -> 99, never 100
  assert.equal(percentFloorCents(3997, 10), 399);
  assert.equal(percentFloorCents(99, 1), 0);      // 0.99 -> 0
  assert.equal(percentFloorCents(1000, 100), 1000);
  assert.throws(() => percentFloorCents(100, 101), RangeError);
});

test('tax percent rounds half-up (engine policy, fractional rates)', () => {
  assert.equal(percentHalfUpCents(1000, 8.875), 89);  // 88.75 -> 89
  assert.equal(percentHalfUpCents(999, 20), 200);     // 199.8 -> 200
  assert.equal(percentHalfUpCents(100, 2.5), 3);      // 2.50 -> 3 (half up)
});

test('CryptoBot gross-up matches handlers/crypto.py integer ceiling', () => {
  // gross = ceil(net * 100 / (100 - fee)); fee = gross - net
  assert.deepEqual(grossUpCents(10000, 3), { grossCents: 10310, feeCents: 310 });
  assert.deepEqual(grossUpCents(2599, 3), { grossCents: 2680, feeCents: 81 });
  assert.deepEqual(grossUpCents(100, 3), { grossCents: 104, feeCents: 4 });
  assert.deepEqual(grossUpCents(5000, 0), { grossCents: 5000, feeCents: 0 });
});

test('splitCents via allocate never loses or invents a cent', () => {
  for (const [amount, ratios] of [[100, [1, 1, 1]], [999, [70, 30]], [5, [1, 1]], [1, [50, 50]]]) {
    const parts = splitCents(amount, ratios);
    assert.equal(parts.reduce((a, b) => a + b, 0), amount, `split of ${amount}`);
    assert.equal(parts.length, ratios.length);
  }
  assert.deepEqual(splitCents(1000, [70, 30]), [700, 300]);
});

test('formatMoney is byte-identical to the bot fmt_money shape', () => {
  assert.equal(formatMoney(1999), '$19.99');
  assert.equal(formatMoney(5), '$0.05');
  assert.equal(formatMoney(0), '$0.00');
  assert.equal(formatMoney(100000), '$1000.00'); // no thousands separator
  assert.equal(formatMoney(-500), '-$5.00');
});

test('priceOrder: gateway gross-up rides on top of the total', () => {
  const out = priceOrder({
    items: [{ priceCents: 10000, qty: 1 }],
    gatewayFee: { feePct: 3 },
  });
  assert.equal(out.total, 10000);
  assert.equal(out.grossTotal, 10310);
  assert.equal(out.gatewayFee, 310);
});

test('priceOrder: tax applies to the discounted base', () => {
  const out = priceOrder({
    items: [{ priceCents: 10000, qty: 1 }],
    promo: { kind: 'percent', value: 10 },
    taxRatePct: 20,
  });
  assert.equal(out.discount, 1000);
  assert.equal(out.tax, 1800); // 20% of 9000
  assert.equal(out.total, 10800);
});

test('priceOrder: total never goes negative', () => {
  const out = priceOrder({
    items: [{ priceCents: 100, qty: 1 }],
    promo: { kind: 'fixed', value: 100 },
  });
  assert.equal(out.total, 0);
});
