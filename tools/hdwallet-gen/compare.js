// compare.js — derive deposit addresses from the bot's xpubs using the OFFICIAL
// trustwallet/wallet-core (npm @trustwallet/wallet-core), then compare with the
// bot's Python hdwallet derivation. Any mismatch = the bot shows wrong addresses.
const { initWasm } = require("@trustwallet/wallet-core");
const fs = require("fs");

const env = {};
for (const line of fs.readFileSync("/home/hatch/workspace/nova-shop/.env", "utf8").split("\n")) {
  const m = line.match(/^([A-Z_]+)=(.*)$/);
  if (m) env[m[1]] = m[2].trim();
}

function addrFromXpub(core, xpub, coin, fullPath) {
  const pubkey = core.HDWallet.getPublicKeyFromExtended(xpub, coin, fullPath);
  const addr = core.CoinTypeExt.deriveAddressFromPublicKey(coin, pubkey);
  pubkey.delete();
  return addr;
}

(async () => {
  const core = await initWasm();
  const { CoinType } = core;
  const jobs = [
    ["btc", env.XPUB_BTC, CoinType.bitcoin, i => `m/84'/0'/0'/0/${i}`],
    ["eth", env.XPUB_ETH, CoinType.ethereum, i => `m/44'/60'/0'/0/${i}`],
    ["trx", env.XPUB_TRX, CoinType.tron, i => `m/44'/195'/0'/0/${i}`],
  ];
  for (const [chain, xpub, coin, pathFn] of jobs) {
    const addrs = [0, 1, 2].map(i => addrFromXpub(core, xpub, coin, pathFn(i)));
    console.log(chain, ...addrs);
  }
})().catch(e => { console.error("FATAL", e.message); process.exit(1); });
