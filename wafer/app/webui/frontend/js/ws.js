export function connectEvents(onEvent, onStatusChange) {
  let ws = null;
  let retry = 1000;

  function connect() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${scheme}://${location.host}/ws`);
    ws.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data));
      } catch (err) {
        console.error('invalid event', err);
      }
    };
    ws.onopen = () => {
      retry = 1000;
      if (onStatusChange) onStatusChange('open');
    };
    ws.onclose = () => {
      if (onStatusChange) onStatusChange('closed');
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 30000);
    };
  }

  connect();
}
