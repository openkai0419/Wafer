export function connectEvents(onEvent) {
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
    };
    ws.onclose = () => {
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 30000);
    };
  }

  connect();
}
