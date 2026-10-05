# Payments Architecture

Nova Shop has multiple rails, but every rail should converge on one internal payment state machine.

## Telegram commerce rule

Telegram's current Payments API states that digital goods and services sold inside Telegram bots and Mini Apps use Telegram Stars.

Therefore the application must classify the order before generating payment options.

~~~text
digital item/service + sold inside Telegram
        ↓
Telegram Stars only

physical goods / permitted service flow
        ↓
provider-specific rail where permitted
~~~

Reference: https://core.telegram.org/bots/payments-stars

This is especially important because the current product model contains both digital and physical goods.

## Rails

- Telegram Stars.
- Card/provider payments where permitted for the order type.
- CryptoBot where permitted.
- Direct self-custody crypto where permitted.
- TON Connect where permitted.
- Cash on delivery for eligible physical orders.

## Canonical payment model

~~~text
Order
  ↓
PaymentIntent
  id
  order_id
  rail
  network
  asset
  expected_amount_atomic
  expected_fiat_cents
  recipient
  memo_or_tag
  quote_id
  expires_at
  ↓
PaymentObservation
  provider
  external_id
  chain-native identity
  amount_atomic
  block / slot / ledger
  observed_at
  state
  ↓
PaymentDecision
  matched
  sufficient
  finality
  claim_state
  ↓
Fulfillment
~~~

## Payment invariants

1. Client totals are never authoritative.
2. Fiat amounts use integer minor units.
3. Crypto amounts use atomic units.
4. Token identity includes network and contract/address.
5. Provider-native identifiers are retained and deduplicated.
6. Replays are harmless.
7. Finality/reorg states are explicit.
8. Late payments remain auditable.
9. Quote source, timestamp, amount and expiry are retained.
10. Manual confirmation is exceptional and audited.
11. Fulfillment is idempotent.
12. Payment observation is evidence to verify, not automatic authorization.

## Chain-native payment identity

~~~text
Bitcoin
  txid + vout

EVM token
  chain_id + token_contract + tx_hash + log_index

TRON token
  transaction/event identity + contract + recipient

TON
  address + comment/memo + transaction/message identity

Solana
  signature + instruction/account/token context
~~~

The exact uniqueness key belongs to the chain adapter.

## Reconciliation

The current 60-second watcher is a near-real-time observer, not the only source of truth.

A durable reconciliation worker should replay a safe overlap window from the last successful cursor and compare observations with the database.

Typical cursors:

Bitcoin → block/UTXO boundary
EVM → block/log boundary
TRON → block/event boundary
TON → transaction/message boundary
Solana → slot/signature boundary
