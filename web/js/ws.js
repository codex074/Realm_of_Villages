// WebSocket client for /ws: lazy connect, auto-reconnect with backoff, ping keepalive.

const BACKOFF_SECONDS = [1, 2, 5, 10];
const PING_INTERVAL_MS = 25000;

let socket = null;
let backoffIndex = 0;
let pingTimer = null;
let reconnectTimer = null;
const listeners = new Set();

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${location.host}/ws`;
}

function connect() {
  socket = new WebSocket(wsUrl());

  socket.onopen = () => {
    backoffIndex = 0;
    pingTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) socket.send('ping');
    }, PING_INTERVAL_MS);
  };

  socket.onmessage = (event) => {
    if (event.data === 'pong') return;
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return; // Ignore unparsable messages.
    }
    if (msg && msg.type === 'changed') {
      for (const cb of listeners) cb(msg);
    }
  };

  socket.onclose = () => {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
    const delay = BACKOFF_SECONDS[Math.min(backoffIndex, BACKOFF_SECONDS.length - 1)] * 1000;
    backoffIndex += 1;
    reconnectTimer = setTimeout(connect, delay);
  };

  socket.onerror = () => {
    // onclose follows and handles the reconnect.
  };
}

// Register a callback for every {type:'changed', kind, village_id} message.
// Returns an unsubscribe function. Connects lazily on first call.
export function onChanged(cb) {
  listeners.add(cb);
  if (socket === null) connect();
  return () => listeners.delete(cb);
}
