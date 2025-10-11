import express from 'express';
import cors from 'cors';

const app = express();
const port = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Simple in-memory real data source: time ticks
function createTimeStream(res) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'Access-Control-Allow-Origin': '*',
  });
  res.write(`retry: 2000\n\n`);

  const sendTick = () => {
    const payload = {
      nowIso: new Date().toISOString(),
      nowEpochMs: Date.now(),
      random: Math.random(),
    };
    res.write(`event: tick\n`);
    res.write(`data: ${JSON.stringify(payload)}\n\n`);
  };

  // Send initial event
  sendTick();
  const intervalId = setInterval(sendTick, 1000);

  const cleanup = () => {
    clearInterval(intervalId);
    try {
      res.end();
    } catch {}
  };
  res.on('close', cleanup);
  res.on('error', cleanup);
}

app.get('/events/time', (req, res) => {
  createTimeStream(res);
});

// Fetch BTC-USD spot price from a public API
async function fetchBtcUsdSpotPrice() {
  // Prefer Coinbase spot price; fallback to Binance if Coinbase fails
  const coinbaseUrl = 'https://api.coinbase.com/v2/prices/BTC-USD/spot';
  const binanceUrl = 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT';

  try {
    const response = await fetch(coinbaseUrl, { headers: { 'Accept': 'application/json' } });
    if (!response.ok) throw new Error(`Coinbase HTTP ${response.status}`);
    const json = await response.json();
    const amount = parseFloat(json?.data?.amount);
    if (!Number.isFinite(amount)) throw new Error('Invalid Coinbase amount');
    return { price: amount, currency: 'USD', source: 'coinbase' };
  } catch (coinbaseError) {
    try {
      const response = await fetch(binanceUrl, { headers: { 'Accept': 'application/json' } });
      if (!response.ok) throw new Error(`Binance HTTP ${response.status}`);
      const json = await response.json();
      const amount = parseFloat(json?.price);
      if (!Number.isFinite(amount)) throw new Error('Invalid Binance price');
      // Binance returns USDT; treat as USD approximation
      return { price: amount, currency: 'USDT', source: 'binance' };
    } catch (binanceError) {
      throw new Error(`Price fetch failed: ${coinbaseError.message}; ${binanceError.message}`);
    }
  }
}

function createBtcUsdPriceStream(res) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'Access-Control-Allow-Origin': '*',
  });
  res.write(`retry: 2000\n\n`);

  let isClosed = false;

  const sendPrice = async () => {
    if (isClosed) return;
    try {
      const result = await fetchBtcUsdSpotPrice();
      const payload = {
        symbol: 'BTC-USD',
        price: result.price,
        currency: result.currency,
        source: result.source,
        fetchedAtIso: new Date().toISOString(),
        fetchedAtEpochMs: Date.now(),
      };
      res.write(`event: price\n`);
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
    } catch (error) {
      const payload = {
        error: String(error?.message || error),
        fetchedAtIso: new Date().toISOString(),
      };
      res.write(`event: price_error\n`);
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
    }
  };

  // Send immediately, then poll periodically
  sendPrice();
  const intervalId = setInterval(sendPrice, 2000);

  const cleanup = () => {
    isClosed = true;
    clearInterval(intervalId);
    try { res.end(); } catch {}
  };
  res.on('close', cleanup);
  res.on('error', cleanup);
}

app.get('/events/price/btcusd', (req, res) => {
  createBtcUsdPriceStream(res);
});

app.get('/', (req, res) => {
  res.type('html').send(`<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Realtime SSE Demo</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica, Arial, \"Apple Color Emoji\", \"Segoe UI Emoji\"; padding: 24px; }
      pre { background: #0b1021; color: #e7eaf6; padding: 12px; border-radius: 8px; overflow: auto; }
      .event { margin-bottom: 12px; }
    </style>
  </head>
  <body>
    <h1>Realtime SSE Demo</h1>
    <p>Conectado a <code>/events/time</code> y <code>/events/price/btcusd</code>.</p>
    <h2>BTC-USD Spot Price</h2>
    <div id="price"></div>
    <h2>Time Ticks</h2>
    <div id="events"></div>
    <script>
      const eventsDiv = document.getElementById('events');
      const es = new EventSource('/events/time');
      es.addEventListener('tick', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const el = document.createElement('div');
          el.className = 'event';
          el.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
          eventsDiv.prepend(el);
          // Keep only last 30
          while (eventsDiv.children.length > 30) eventsDiv.removeChild(eventsDiv.lastChild);
        } catch (e) { console.error(e); }
      });
      es.onerror = (e) => {
        const el = document.createElement('div');
        el.className = 'event';
        el.textContent = 'Error de conexión SSE, reintentando...';
        eventsDiv.prepend(el);
      };

      // Price feed
      const priceDiv = document.getElementById('price');
      const esPrice = new EventSource('/events/price/btcusd');
      esPrice.addEventListener('price', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          priceDiv.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
        } catch (e) { console.error(e); }
      });
      esPrice.addEventListener('price_error', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const el = document.createElement('div');
          el.className = 'event';
          el.textContent = 'Error al obtener precio: ' + data.error;
          priceDiv.prepend(el);
        } catch (e) { console.error(e); }
      });
    </script>
  </body>
</html>`);
});

app.listen(port, () => {
  console.log(`Servidor en http://localhost:${port}`);
});
