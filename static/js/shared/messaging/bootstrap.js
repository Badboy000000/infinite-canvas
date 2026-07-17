(function installStudioMessagingBootstrap(global) {
  'use strict';

  // Update this digest whenever an ESM file under shared/messaging changes.
  // tests/frontend/test_shared_messaging_storage.py enforces the source digest.
  const MESSAGING_MODULE_VERSION = '60494ee6b11b';
  const DEFAULT_TYPES = Object.freeze([
    'providers-changed',
    'workflows-changed',
    'comfy-instances-changed',
  ]);

  function stableValue(value, ancestors) {
    if (value === null || typeof value !== 'object') return value;
    if (ancestors.has(value)) return '[circular]';
    ancestors.add(value);
    const result = Array.isArray(value)
      ? value.map(item => stableValue(item, ancestors))
      : Object.fromEntries(Object.keys(value).sort().map(key => [key, stableValue(value[key], ancestors)]));
    ancestors.delete(value);
    return result;
  }

  function dedupeKey(message) {
    if (message?.message_id) return `id:${message.message_id}`;
    try { return `legacy:${JSON.stringify(stableValue(message, new Set()))}`; } catch (_) { return null; }
  }

  function createRecentMessages(windowMs) {
    const seen = new Map();
    return {
      accept(message) {
        const key = dedupeKey(message);
        if (!key) return true;
        const now = Date.now();
        const previous = seen.get(key);
        seen.set(key, now);
        if (seen.size > 512) seen.delete(seen.keys().next().value);
        return previous === undefined || now - previous > windowMs;
      },
    };
  }

  function createMessagingBootstrap({
    loadModule,
    windowRef = global.window,
    BroadcastChannelImpl = global.BroadcastChannel,
    legacyDedupeWindowMs = 500,
  } = {}) {
    if (typeof loadModule !== 'function') throw new TypeError('loadModule must be a function');
    const moduleReady = Promise.resolve().then(loadModule);

    function connect({
      localClientId = null,
      types = DEFAULT_TYPES,
      onMessage = function noop() {},
      storageEvent = null,
    } = {}) {
      const acceptedTypes = new Set(types);
      const recent = createRecentMessages(legacyDedupeWindowMs);
      const earlyMessages = [];
      const socketAttachments = new Set();
      let bus = null;
      let channel = null;
      let closed = false;

      function dispatch(message) {
        if (!message || !acceptedTypes.has(message.type) || !recent.accept(message)) return false;
        earlyMessages.push(message);
        if (earlyMessages.length > 512) earlyMessages.shift();
        onMessage(message);
        return true;
      }

      const messageListener = event => {
        const expectedOrigin = windowRef?.location?.origin;
        if (event.origin && expectedOrigin && event.origin !== expectedOrigin) return;
        dispatch(event.data);
      };
      windowRef?.addEventListener?.('message', messageListener);

      if (typeof BroadcastChannelImpl === 'function') {
        try {
          channel = new BroadcastChannelImpl('studio-api');
          channel.addEventListener?.('message', event => dispatch(event.data));
          if (!channel.addEventListener) channel.onmessage = event => dispatch(event.data);
        } catch (_) {
          channel = null;
        }
      }

      const storageListener = storageEvent?.toMessage
        ? event => {
            const message = storageEvent.toMessage(event);
            if (message) dispatch(message);
          }
        : null;
      if (storageListener) {
        (storageEvent.windowRef || windowRef)?.addEventListener?.('storage', storageListener);
      }

      function detachLegacyListeners() {
        windowRef?.removeEventListener?.('message', messageListener);
        channel?.close?.();
        channel = null;
        if (storageListener) {
          (storageEvent.windowRef || windowRef)?.removeEventListener?.('storage', storageListener);
        }
      }

      function detachSocketFallback(attachment) {
        if (attachment.listener) {
          attachment.socket?.removeEventListener?.('message', attachment.listener);
          attachment.listener = null;
        }
      }

      function attachWebSocket(socket) {
        const attachment = { socket, listener: null };
        attachment.listener = event => {
          try {
            dispatch(typeof event.data === 'string' ? JSON.parse(event.data) : event.data);
          } catch (_) {}
        };
        socket?.addEventListener?.('message', attachment.listener);
        socketAttachments.add(attachment);
        if (bus) {
          detachSocketFallback(attachment);
          moduleReady.then(module => bus?.addBridge(module.createWebSocketBridge({ socket })));
        }
        return () => {
          detachSocketFallback(attachment);
          socketAttachments.delete(attachment);
        };
      }

      const ready = moduleReady.then(module => {
        if (closed) return null;
        const extraBridges = [...socketAttachments].map(attachment => (
          module.createWebSocketBridge({ socket: attachment.socket })
        ));
        bus = module.createStudioBus({
          localClientId,
          windowRef,
          BroadcastChannelImpl,
          storageEvent,
          extraBridges,
          initialMessages: earlyMessages,
          legacyDedupeWindowMs,
        });
        acceptedTypes.forEach(type => bus.on(type, onMessage));
        detachLegacyListeners();
        socketAttachments.forEach(detachSocketFallback);
        return bus;
      }).catch(() => null);

      return Object.freeze({
        ready,
        emit(message) {
          if (bus) return bus.emit(message);
          try { channel?.postMessage?.(message); } catch (_) {}
          const targets = new Set([windowRef?.parent, windowRef?.top].filter(Boolean));
          targets.forEach(target => {
            if (target === windowRef) return;
            try {
              const origin = windowRef?.location?.origin || '*';
              target.postMessage(message, origin === 'null' ? '*' : origin);
            } catch (_) {}
          });
          return message;
        },
        attachWebSocket,
        close() {
          closed = true;
          detachLegacyListeners();
          socketAttachments.forEach(detachSocketFallback);
          socketAttachments.clear();
          bus?.close();
        },
      });
    }

    return Object.freeze({ connect, moduleReady });
  }

  global.StudioMessagingBootstrap = Object.freeze({
    createMessagingBootstrap,
    moduleVersion: MESSAGING_MODULE_VERSION,
  });

  const currentScript = global.document?.currentScript;
  if (currentScript?.src) {
    const moduleUrl = new URL('./index.js', currentScript.src);
    moduleUrl.search = `?v=${encodeURIComponent(MESSAGING_MODULE_VERSION)}`;
    global.StudioMessaging = createMessagingBootstrap({
      loadModule: () => import(moduleUrl.href),
      windowRef: global.window,
      BroadcastChannelImpl: global.BroadcastChannel,
    });
  }
})(globalThis);
