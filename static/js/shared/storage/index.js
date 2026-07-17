import { namespacedKey } from './namespaced.js';
export { LegacyStorageKey, LEGACY_STORAGE_KEYS } from './legacyKeys.js';
export { namespacedKey } from './namespaced.js';

function resolveStorage(kind) {
  return kind === 'session' ? globalThis.sessionStorage : globalThis.localStorage;
}

export const sharedStorage = Object.freeze({
  get(key, { schema = 'string', storage = 'local', fallback = null } = {}) {
    const raw = resolveStorage(storage)?.getItem(key);
    if (raw === null || raw === undefined) return fallback;
    if (schema === 'json') {
      try { return JSON.parse(raw); } catch (_) { return fallback; }
    }
    return raw;
  },
  set(key, value, { schema = 'string', storage = 'local' } = {}) {
    const raw = schema === 'json' ? JSON.stringify(value) : String(value);
    resolveStorage(storage)?.setItem(key, raw);
    return value;
  },
  remove(key, { storage = 'local' } = {}) {
    resolveStorage(storage)?.removeItem(key);
  },
  key: namespacedKey,
});
