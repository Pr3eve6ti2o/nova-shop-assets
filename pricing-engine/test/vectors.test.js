/**
 * Shared-vector parity: every case in ../test-vectors.json must price
 * identically in this JS engine and in the Python bot (the same file is
 * executed against the bot's real totals() by
 * bot/tests/test_pricing_parity.py). If the two ever disagree, one side
 * changed the money rules without the other — fail loudly.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { priceOrder } from '../src/index.js';

const { vectors } = JSON.parse(
  readFileSync(new URL('../test-vectors.json', import.meta.url), 'utf8'),
);

for (const v of vectors) {
  test(`vector: ${v.name}`, () => {
    const out = priceOrder({
      items: v.items,
      promo: v.promo,
      deliveryFeeCents: v.deliveryFeeCents,
    });
    assert.equal(out.subtotal, v.expected.subtotal, 'subtotal');
    assert.equal(out.discountBasis, v.expected.discountBasis, 'discountBasis');
    assert.equal(out.discount, v.expected.discount, 'discount');
    assert.equal(out.deliveryFee, v.expected.deliveryFee, 'deliveryFee');
    assert.equal(out.total, v.expected.total, 'total');
    assert.equal(out.tax, 0, 'vectors carry no tax (bot parity)');
  });
}
