function defaultOrigin(windowRef) {
  const origin = windowRef?.location?.origin;
  return origin && origin !== 'null' ? origin : '*';
}

export function isAcceptedMessageOrigin(origin, expectedOrigin) {
  // Empty origin was accepted by the legacy handlers and is retained for opaque local contexts.
  return !origin || origin === expectedOrigin;
}

export function createIframeMessageBridge({
  windowRef = globalThis.window,
  expectedOrigin = windowRef?.location?.origin,
  targets = () => [windowRef?.parent, windowRef?.top],
  targetOrigin = defaultOrigin(windowRef),
} = {}) {
  let listener = null;

  return {
    name: 'iframeMessage',
    start(receive) {
      if (!windowRef?.addEventListener) return;
      listener = event => {
        if (!isAcceptedMessageOrigin(event.origin, expectedOrigin)) return;
        receive(event.data);
      };
      windowRef.addEventListener('message', listener);
    },
    send(message) {
      const uniqueTargets = new Set((targets?.() || []).filter(Boolean));
      uniqueTargets.forEach(target => {
        if (target === windowRef) return;
        try { target.postMessage(message, targetOrigin); } catch (_) {}
      });
    },
    close() {
      if (listener) windowRef?.removeEventListener?.('message', listener);
      listener = null;
    },
  };
}
