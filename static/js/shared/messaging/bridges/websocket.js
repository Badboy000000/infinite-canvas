export function createWebSocketBridge({ socket, parse = JSON.parse } = {}) {
  let listener = null;
  return {
    name: 'websocket',
    start(receive) {
      if (!socket?.addEventListener) return;
      listener = event => {
        try { receive(typeof event.data === 'string' ? parse(event.data) : event.data); } catch (_) {}
      };
      socket.addEventListener('message', listener);
    },
    send(message) {
      if (socket?.readyState === 1) socket.send(JSON.stringify(message));
    },
    close() {
      if (listener) socket?.removeEventListener?.('message', listener);
      listener = null;
    },
  };
}
