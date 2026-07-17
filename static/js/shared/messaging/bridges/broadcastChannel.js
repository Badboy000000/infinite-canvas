export function createBroadcastChannelBridge({
  channelName = 'studio-api',
  BroadcastChannelImpl = globalThis.BroadcastChannel,
} = {}) {
  let channel = null;
  let receive = null;

  return {
    name: 'broadcastChannel',
    start(handler) {
      receive = handler;
      if (typeof BroadcastChannelImpl !== 'function') return;
      try {
        channel = new BroadcastChannelImpl(channelName);
        channel.addEventListener?.('message', event => receive?.(event.data));
        if (!channel.addEventListener) channel.onmessage = event => receive?.(event.data);
      } catch (_) {
        channel = null;
      }
    },
    send(message) {
      channel?.postMessage(message);
    },
    close() {
      channel?.close?.();
      channel = null;
      receive = null;
    },
  };
}
