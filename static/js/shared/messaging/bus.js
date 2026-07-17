import { assertStudioMessage, isStudioMessage } from './types.js';
import { createBroadcastChannelBridge } from './bridges/broadcastChannel.js';
import { createIframeMessageBridge } from './bridges/iframeMessage.js';
import { createWebSocketBridge } from './bridges/websocket.js';
import { createStorageEventBridge } from './bridges/storageEvent.js';

function messageId() {
  try { return globalThis.crypto?.randomUUID?.() || fallbackMessageId(); } catch (_) { return fallbackMessageId(); }
}

function fallbackMessageId() {
  return `studio_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

function stableValue(value, ancestors = new Set()) {
  if (value === null || typeof value !== 'object') return value;
  if (ancestors.has(value)) return '[circular]';
  ancestors.add(value);
  const result = Array.isArray(value)
    ? value.map(item => stableValue(item, ancestors))
    : Object.fromEntries(Object.keys(value).sort().map(key => [key, stableValue(value[key], ancestors)]));
  ancestors.delete(value);
  return result;
}

export function messageDedupeKey(message) {
  if (message?.message_id) return `id:${message.message_id}`;
  try { return `legacy:${JSON.stringify(stableValue(message))}`; } catch (_) { return null; }
}

export function createMessageBus({
  localClientId = null,
  bridges = [],
  dedupeLimit = 512,
  legacyDedupeWindowMs = 500,
  initialMessages = [],
} = {}) {
  const handlers = new Map();
  const seen = new Map();
  const bridgeMap = new Map(bridges.map(bridge => [bridge.name, bridge]));

  function remember(message) {
    const key = messageDedupeKey(message);
    if (!key) return false;
    const now = Date.now();
    const previous = seen.get(key);
    const isLegacy = key.startsWith('legacy:');
    if (previous !== undefined && (!isLegacy || now - previous <= legacyDedupeWindowMs)) return true;
    seen.set(key, now);
    while (seen.size > dedupeLimit) seen.delete(seen.keys().next().value);
    return false;
  }

  function receive(message) {
    if (!isStudioMessage(message)) return false;
    if (message.client_id && localClientId && message.client_id === localClientId) return false;
    if (remember(message)) return false;
    [...(handlers.get(message.type) || [])].forEach(handler => handler(message));
    return true;
  }

  initialMessages.forEach(message => remember(message));
  bridges.forEach(bridge => bridge.start(receive));

  function addBridge(bridge) {
    if (!bridge?.name || typeof bridge.start !== 'function') {
      throw new TypeError('Message bridge must have a name and start(handler)');
    }
    const previous = bridgeMap.get(bridge.name);
    if (previous && previous !== bridge) {
      previous.close?.();
      const index = bridges.indexOf(previous);
      if (index >= 0) bridges.splice(index, 1);
    }
    bridgeMap.set(bridge.name, bridge);
    bridges.push(bridge);
    bridge.start(receive);
    return () => {
      if (bridgeMap.get(bridge.name) === bridge) bridgeMap.delete(bridge.name);
      const index = bridges.indexOf(bridge);
      if (index >= 0) bridges.splice(index, 1);
      bridge.close?.();
    };
  }

  return Object.freeze({
    emit(messageOrType, payload = {}, options = {}) {
      const base = typeof messageOrType === 'string'
        ? { ...payload, type: messageOrType }
        : { ...messageOrType };
      assertStudioMessage(base);
      const message = { ...base, message_id: base.message_id || messageId() };
      receive(message);
      const selected = options.bridges || [...bridgeMap.keys()];
      selected.forEach(name => bridgeMap.get(name)?.send(message));
      return message;
    },
    on(type, handler) {
      if (typeof handler !== 'function') throw new TypeError('Message handler must be a function');
      const set = handlers.get(type) || new Set();
      set.add(handler);
      handlers.set(type, set);
      return () => set.delete(handler);
    },
    off(type, handler) {
      return handlers.get(type)?.delete(handler) || false;
    },
    once(type, handler) {
      let unsubscribe = null;
      unsubscribe = this.on(type, message => {
        unsubscribe?.();
        handler(message);
      });
      return unsubscribe;
    },
    receive,
    addBridge,
    close() {
      bridges.forEach(bridge => bridge.close?.());
      handlers.clear();
      seen.clear();
    },
  });
}

export function createStudioBus({
  localClientId = null,
  windowRef = globalThis.window,
  BroadcastChannelImpl = globalThis.BroadcastChannel,
  iframeTargets,
  socket = null,
  storageEvent = null,
  extraBridges = [],
  initialMessages = [],
  legacyDedupeWindowMs = 500,
} = {}) {
  const bridges = [
    createBroadcastChannelBridge({ BroadcastChannelImpl }),
    createIframeMessageBridge({ windowRef, targets: iframeTargets }),
    ...(socket ? [createWebSocketBridge({ socket })] : []),
    ...(storageEvent ? [createStorageEventBridge({ windowRef, ...storageEvent })] : []),
    ...extraBridges,
  ];
  return createMessageBus({ localClientId, bridges, initialMessages, legacyDedupeWindowMs });
}
