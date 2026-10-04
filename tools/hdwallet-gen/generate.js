// generate.js — Trust Wallet wallet-core HD wallet generation for Nova Shop Bot.
// Step 1: validate the install against official test vectors.
// Step 2: generate a fresh 24-word wallet, export xpubs (BTC/ETH/TRX) + TON address.
// Outputs one JSON object on stdout. The mnemonic is included — pipe, don't log.
const { initWasm } = require("@trustwallet/wallet-core");

const VEC_MNEMONIC = "ripple scissors kick mammal hire column oak again sun offer wealth tomorrow wagon turn fatal";
const VEC = {
  btc: "bc1qpsp72plnsqe6e2dvtsetxtww2cz36ztmfxghpd",   // m/84'/0'/0'/0/0, empty passphrase
  eth: "0xA3Dcd899C0f3832DFDFed9479a9d828c6A4EB2A7",   // m/44'/60'/0'/0/0
  eth1: "0x68eF4e5660620976a5968c7d7925753D3Cc40809",  // m/44'/60'/1'/0/0
};

function addrFromExtended(core, xpub, coin, path) {
  const pubkey = core.HDWallet.getPublicKeyFromExtended(xpub, coin, path);
  const addr = core.CoinTypeExt.derivationPath
    ? core.CoinTypeExt.deriveAddressFromPublicKey(coin, pubkey)
    : null;
  pubkey.delete();
  return addr;
}

(async () => {
  const core = await initWasm();
  const { HDWallet, CoinType, CoinTypeExt, Purpose, Derivation, HDVersion } = core;
  const checks = [];
  const ok = (name, cond) => { checks.push({ name, ok: !!cond }); if (!cond) throw new Error("CHECK FAILED: " + name); };

  ok("coin_tron_195", CoinType.tron.value === 195);
  ok("coin_ton_607", CoinType.ton.value === 607);

  // ---- Step 1: test vectors (empty passphrase) ----
  const v = HDWallet.createWithMnemonic(VEC_MNEMONIC, "");
  ok("vec_btc", v.getAddressForCoin(CoinType.bitcoin) === VEC.btc);
  ok("vec_eth", v.getAddressForCoin(CoinType.ethereum) === VEC.eth);

  // extended-key roundtrips on the vector wallet
  const vBtcZpub = v.getExtendedPublicKeyAccount(Purpose.bip84, CoinType.bitcoin, Derivation.bitcoinSegwit, HDVersion.zpub, 0);
  ok("vec_zpub_prefix", vBtcZpub.startsWith("zpub"));
  ok("vec_zpub_addr0", addrFromExtended(core, vBtcZpub, CoinType.bitcoin, "m/84'/0'/0'/0/0") === VEC.btc);
  ok("vec_zpub_addr1_valid", CoinTypeExt.validate(CoinType.bitcoin, addrFromExtended(core, vBtcZpub, CoinType.bitcoin, "m/84'/0'/0'/0/1")));

  const vEthXpub = v.getExtendedPublicKeyAccount(Purpose.bip44, CoinType.ethereum, Derivation.default, HDVersion.xpub, 0);
  ok("vec_ethxpub_prefix", vEthXpub.startsWith("xpub"));
  ok("vec_ethxpub_addr0", addrFromExtended(core, vEthXpub, CoinType.ethereum, "m/44'/60'/0'/0/0") === VEC.eth);

  const vTrxXpub = v.getExtendedPublicKeyAccount(Purpose.bip44, CoinType.tron, Derivation.default, HDVersion.xpub, 0);
  ok("vec_trxxpub_prefix", vTrxXpub.startsWith("xpub"));
  ok("vec_trxxpub_addr0", addrFromExtended(core, vTrxXpub, CoinType.tron, "m/44'/195'/0'/0/0") === v.getAddressForCoin(CoinType.tron));
  ok("vec_trx_valid", CoinTypeExt.validate(CoinType.tron, v.getAddressForCoin(CoinType.tron)));
  v.delete();

  // ---- Step 2: fresh wallet (24 words, empty passphrase) ----
  const w = HDWallet.create(256, "");
  const mnemonic = w.mnemonic();
  ok("mnemonic_24_words", mnemonic.trim().split(/\s+/).length === 24 && core.Mnemonic.isValid(mnemonic));

  const btcZpub = w.getExtendedPublicKeyAccount(Purpose.bip84, CoinType.bitcoin, Derivation.bitcoinSegwit, HDVersion.zpub, 0);
  const ethXpub = w.getExtendedPublicKeyAccount(Purpose.bip44, CoinType.ethereum, Derivation.default, HDVersion.xpub, 0);
  const trxXpub = w.getExtendedPublicKeyAccount(Purpose.bip44, CoinType.tron, Derivation.default, HDVersion.xpub, 0);
  const tonAddress = w.getAddressForCoin(CoinType.ton);

  ok("btc_zpub_prefix", btcZpub.startsWith("zpub"));
  ok("eth_xpub_prefix", ethXpub.startsWith("xpub"));
  ok("trx_xpub_prefix", trxXpub.startsWith("xpub"));
  ok("ton_valid", CoinTypeExt.validate(CoinType.ton, tonAddress));

  // cross-check: extended key -> address must equal wallet default address
  ok("btc_roundtrip", addrFromExtended(core, btcZpub, CoinType.bitcoin, "m/84'/0'/0'/0/0") === w.getAddressForCoin(CoinType.bitcoin));
  ok("eth_roundtrip", addrFromExtended(core, ethXpub, CoinType.ethereum, "m/44'/60'/0'/0/0") === w.getAddressForCoin(CoinType.ethereum));
  ok("trx_roundtrip", addrFromExtended(core, trxXpub, CoinType.tron, "m/44'/195'/0'/0/0") === w.getAddressForCoin(CoinType.tron));

  // sample deposit addresses (index 1, since index 0 is reserved by the bot)
  const samples = {
    btc1: addrFromExtended(core, btcZpub, CoinType.bitcoin, "m/84'/0'/0'/0/1"),
    eth1: addrFromExtended(core, ethXpub, CoinType.ethereum, "m/44'/60'/0'/0/1"),
    trx1: addrFromExtended(core, trxXpub, CoinType.tron, "m/44'/195'/0'/0/1"),
  };
  w.delete(); // memzero seed/mnemonic in WASM heap

  console.log(JSON.stringify({
    mnemonic,
    btc_zpub: btcZpub,
    eth_xpub: ethXpub,
    trx_xpub: trxXpub,
    ton_address: tonAddress,
    ton_path: CoinTypeExt.derivationPath(CoinType.ton),
    samples,
    checks,
    wallet_core_version: require("@trustwallet/wallet-core/package.json").version,
  }));
})().catch(e => { console.error("FATAL: " + e.message); process.exit(1); });
