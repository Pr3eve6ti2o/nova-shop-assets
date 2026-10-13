/**
 * Browser entry for the Mini App bundle. The full engine API is exposed
 * as window.NovaPricing; app.js uses it when present and falls back to
 * its built-in integer math when absent (e.g. stale cached bundle), so
 * the storefront can never be broken by a missing engine.
 */
import { NovaPricing } from './index.js';

window.NovaPricing = NovaPricing;
