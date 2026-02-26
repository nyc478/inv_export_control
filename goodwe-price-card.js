class GoodWePriceCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    this._config = config;
    this._entity = config.entity || "sensor.day_ahead_energy_price";
  }

  _render() {
    const state = this._hass.states[this._entity];
    if (!state) {
      this.innerHTML = `<ha-card><div class="error">Entity ${this._entity} not found</div></ha-card>`;
      return;
    }

    const currentPrice = parseFloat(state.state);
    const upcoming = state.attributes.upcoming_prices || [];
    const blockExport = state.attributes.block_export;

    // Split into today and tomorrow
    const now = new Date();
    const todayStr = now.toISOString().slice(0, 10);
    const tomorrowStr = new Date(now.getTime() + 86400000).toISOString().slice(0, 10);

    const today = upcoming.filter(p => p.time.startsWith(todayStr));
    const tomorrow = upcoming.filter(p => p.time.startsWith(tomorrowStr));

    const allPrices = upcoming.map(p => p.price_eur_mwh);
    const minPrice = Math.min(...allPrices);
    const maxPrice = Math.max(...allPrices);

    const priceColor = (p) => {
      if (p <= 0) return "var(--price-negative)";
      if (p < 50) return "var(--price-low)";
      if (p < 120) return "var(--price-mid)";
      return "var(--price-high)";
    };

    const barHeight = (p) => {
      const range = maxPrice - minPrice || 1;
      return Math.max(4, Math.round(((p - minPrice) / range) * 80));
    };

    const formatTime = (iso) => {
      const d = new Date(iso);
      return d.toLocaleTimeString("el-GR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Athens" });
    };

    const formatPrice = (p) => `${p.toFixed(1)}`;

    const isCurrentHour = (iso) => {
      const d = new Date(iso);
      return d.getHours() === now.getHours() && iso.startsWith(todayStr);
    };

    const renderBars = (prices) => prices.map(p => `
      <div class="bar-wrap ${isCurrentHour(p.time) ? "current" : ""}" title="${formatTime(p.time)}: ${p.price_eur_mwh} €/MWh">
        <div class="bar-label">${formatPrice(p.price_eur_mwh)}</div>
        <div class="bar-outer">
          <div class="bar-inner" style="height:${barHeight(p.price_eur_mwh)}px; background:${priceColor(p.price_eur_mwh)}"></div>
        </div>
        <div class="bar-time">${formatTime(p.time)}</div>
      </div>
    `).join("");

    this.innerHTML = `
      <ha-card>
        <style>
          :host {
            --price-negative: #ef4444;
            --price-low: #22c55e;
            --price-mid: #f59e0b;
            --price-high: #ef4444;
            --bg: #0f172a;
            --surface: #1e293b;
            --border: #334155;
            --text: #f1f5f9;
            --muted: #94a3b8;
            --accent: #38bdf8;
          }
          ha-card {
            background: var(--bg);
            color: var(--text);
            border-radius: 16px;
            overflow: hidden;
            font-family: 'DM Mono', 'Courier New', monospace;
            border: 1px solid var(--border);
          }
          .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 20px 12px;
            border-bottom: 1px solid var(--border);
          }
          .title {
            font-size: 11px;
            letter-spacing: 0.15em;
            text-transform: uppercase;
            color: var(--muted);
          }
          .current-price {
            display: flex;
            align-items: baseline;
            gap: 4px;
          }
          .price-value {
            font-size: 32px;
            font-weight: 700;
            line-height: 1;
            letter-spacing: -0.02em;
          }
          .price-unit {
            font-size: 12px;
            color: var(--muted);
          }
          .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
          }
          .status-blocked { background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }
          .status-allowed { background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); }
          .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
          .section {
            padding: 14px 20px 8px;
          }
          .section-title {
            font-size: 10px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--muted);
            margin-bottom: 12px;
          }
          .chart {
            display: flex;
            align-items: flex-end;
            gap: 2px;
            overflow-x: auto;
            padding-bottom: 4px;
            scrollbar-width: none;
          }
          .chart::-webkit-scrollbar { display: none; }
          .bar-wrap {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 3px;
            flex-shrink: 0;
            width: 28px;
            cursor: default;
          }
          .bar-wrap.current .bar-outer {
            box-shadow: 0 0 8px var(--accent);
          }
          .bar-wrap.current .bar-time {
            color: var(--accent);
            font-weight: 700;
          }
          .bar-label {
            font-size: 7px;
            color: var(--muted);
            white-space: nowrap;
          }
          .bar-outer {
            width: 18px;
            height: 90px;
            display: flex;
            align-items: flex-end;
            background: var(--surface);
            border-radius: 4px 4px 0 0;
            overflow: hidden;
          }
          .bar-inner {
            width: 100%;
            border-radius: 4px 4px 0 0;
            transition: height 0.3s ease;
          }
          .bar-time {
            font-size: 7px;
            color: var(--muted);
            transform: rotate(-45deg);
            white-space: nowrap;
            margin-top: 4px;
          }
          .divider { height: 1px; background: var(--border); margin: 0 20px; }
          .no-data {
            padding: 20px;
            text-align: center;
            color: var(--muted);
            font-size: 12px;
          }
          .stat-row {
            display: flex;
            gap: 12px;
            padding: 10px 20px 16px;
          }
          .stat {
            flex: 1;
            background: var(--surface);
            border-radius: 8px;
            padding: 10px 12px;
            border: 1px solid var(--border);
          }
          .stat-label { font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
          .stat-value { font-size: 18px; font-weight: 700; margin-top: 2px; }
        </style>

        <div class="header">
          <div>
            <div class="title">⚡ Energy Price</div>
            <div class="current-price">
              <span class="price-value" style="color:${priceColor(currentPrice)}">${isNaN(currentPrice) ? "—" : formatPrice(currentPrice)}</span>
              <span class="price-unit">€/MWh</span>
            </div>
          </div>
          <div class="status-badge ${blockExport ? "status-blocked" : "status-allowed"}">
            <div class="dot"></div>
            ${blockExport ? "Export Off" : "Exporting"}
          </div>
        </div>

        ${today.length > 0 ? `
          <div class="section">
            <div class="section-title">Today</div>
            <div class="chart">${renderBars(today)}</div>
          </div>
        ` : ""}

        ${today.length > 0 && tomorrow.length > 0 ? `<div class="divider"></div>` : ""}

        ${tomorrow.length > 0 ? `
          <div class="section">
            <div class="section-title">Tomorrow</div>
            <div class="chart">${renderBars(tomorrow)}</div>
          </div>
        ` : `
          <div class="no-data">Tomorrow's prices not yet published (after ~13:00 CET)</div>
        `}

        ${allPrices.length > 0 ? `
          <div class="stat-row">
            <div class="stat">
              <div class="stat-label">Min</div>
              <div class="stat-value" style="color:${priceColor(minPrice)}">${formatPrice(minPrice)}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Max</div>
              <div class="stat-value" style="color:${priceColor(maxPrice)}">${formatPrice(maxPrice)}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Avg</div>
              <div class="stat-value">${formatPrice(allPrices.reduce((a,b)=>a+b,0)/allPrices.length)}</div>
            </div>
          </div>
        ` : ""}
      </ha-card>
    `;
  }

  getCardSize() { return 4; }

  static getConfigElement() {
    return document.createElement("goodwe-price-card-editor");
  }

  static getStubConfig() {
    return { entity: "sensor.day_ahead_energy_price" };
  }
}

customElements.define("goodwe-price-card", GoodWePriceCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "goodwe-price-card",
  name: "GoodWe Day-Ahead Price",
  description: "Shows today & tomorrow energy prices with export status",
});
