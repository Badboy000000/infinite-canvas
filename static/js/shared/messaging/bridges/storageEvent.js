export function createStorageEventBridge({
  windowRef = globalThis.window,
  toMessage,
  storage = globalThis.localStorage,
} = {}) {
  let listener = null;
  return {
    name: 'storageEvent',
    start(receive) {
      if (!windowRef?.addEventListener || typeof toMessage !== 'function') return;
      listener = event => {
        const message = toMessage(event);
        if (message) receive(message);
      };
      windowRef.addEventListener('storage', listener);
    },
    send(message) {
      if (!message?.storage_key || !storage?.setItem) return;
      storage.setItem(message.storage_key, String(message.storage_value ?? ''));
    },
    close() {
      if (listener) windowRef?.removeEventListener?.('storage', listener);
      listener = null;
    },
  };
}
