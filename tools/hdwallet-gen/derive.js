// derive.js — derive a deposit address from an account xpub using the OFFICIAL
// trustwallet/wallet-core (trustwallet/wallet-core on GitHub, npm
// @trustwallet/wallet-core). Used by the bot at runtime for every direct-crypto
// deposit address, so the addresses shown to users come from Trust Wallet's own
// code, not a third-party reimplementation.
//
// Usage: node derive.js <chain> <xpub> <index>
//   chain: btc | eth | trx
//   xpub:  account-level extended public key (zpub for btc, xpub for eth/trx)
//   index: external-chain child index (0, 1, 2, ...)
// Prints the address on stdout. Exits non-zero on failure.
const { initWasm } = require("@trustwallet/wallet-core");

const CHAINS = {
  btc: (coin) => coin.bitcoin,
  eth: (coin) => coin.ethereum,
  trx: (coin) => coin.tron,
};
const PATHS = {
  btc: (i) => `m/84'/0'/0'/0/${i}`,
  eth: (i) => `m/44'/60'/0'/0/${i}`,
  trx: (i) => `m/44'/195'/0'/0/${i}`,
};

(async () => {
  const [chain, xpub, indexRaw] = process.argv.slice(2);
  const index = Number(indexRaw);
  if (!CHAINS[chain] || !xpub || !Number.isInteger(index) || index < 0) {
    console.error("usage: node derive.js <btc|eth|trx> <xpub> <index>");
    process.exit(2);
  }
  const core = await initWasm();
  const coin = CHAINS[chain](core.CoinType);
  let pubkey;
  try {
    pubkey = core.HDWallet.getPublicKeyFromExtended(xpub.trim(), coin, PATHS[chain](index));
  } catch (e) {
    console.error("getPublicKeyFromExtended failed: " + e.message);
    process.exit(1);
  }
  let addr;
  try {
    addr = core.CoinTypeExt.deriveAddressFromPublicKey(coin, pubkey);
  } catch (e) {
    console.error("deriveAddressFromPublicKey failed: " + e.message);
    process.exit(1);
  } finally {
    pubkey.delete();
  }
  if (!addr || !core.CoinTypeExt.validate(coin, addr)) {
    console.error("derived address failed validation");
    process.exit(1);
  }
  console.log(addr);
})().catch((e) => { console.error("FATAL: " + e.message); process.exit(1); });
