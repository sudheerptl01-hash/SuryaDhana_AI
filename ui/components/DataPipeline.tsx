export function DataPipeline() {
  return (
    <div className="space-y-12">
      {/* Title */}
      <div className="text-center">
        <h2 className="text-4xl font-bold bg-gradient-to-r from-mint-600 to-lavender-600 bg-clip-text text-transparent mb-4">
          ⚙️ Data Pipeline Architecture
        </h2>
        <p className="text-lg text-slate-600">Real-time flow from NSE → DuckDB → Analytics</p>
      </div>

      {/* Pipeline Flow */}
      <div className="space-y-8">
        {/* Stage 1: Data Ingestion */}
        <div className="bg-gradient-to-r from-coral-50 to-coral-100 rounded-xl p-8 border-2 border-coral-300 shadow-lg">
          <div className="flex flex-col md:flex-row items-center gap-6">
            <div className="flex-1">
              <h3 className="text-2xl font-bold text-coral-900 mb-3">📥 Stage 1: Data Ingestion</h3>
              <ul className="space-y-2 text-coral-800">
                <li className="flex items-center gap-2">
                  <span className="text-coral-600 font-bold">→</span> yfinance: 5-year historical OHLCV (batch daily)
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-coral-600 font-bold">→</span> ICICI Breeze API: Live quotes (9:15-15:30 IST)
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-coral-600 font-bold">→</span> 504 Nifty 500 tickers from NSE live CSV
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-coral-600 font-bold">→</span> Smart incremental sync (only fetch missing days)
                </li>
              </ul>
            </div>
            <div className="text-6xl">📡</div>
          </div>
          <div className="mt-4 p-4 bg-white/60 rounded-lg border border-coral-200">
            <code className="text-sm text-slate-700">
              <strong>Script:</strong> scripts/nifty500_pipeline.py<br/>
              <strong>Modes:</strong> initial · daily · enrich · filter · status · reset
            </code>
          </div>
        </div>

        {/* Arrow */}
        <div className="flex justify-center">
          <div className="text-4xl text-slate-400">↓</div>
        </div>

        {/* Stage 2: Database Storage */}
        <div className="bg-gradient-to-r from-mint-50 to-mint-100 rounded-xl p-8 border-2 border-mint-400 shadow-lg">
          <div className="flex flex-col md:flex-row items-center gap-6">
            <div className="flex-1">
              <h3 className="text-2xl font-bold text-mint-900 mb-3">💾 Stage 2: DuckDB Storage</h3>
              <ul className="space-y-2 text-mint-800">
                <li className="flex items-center gap-2">
                  <span className="text-mint-600 font-bold">→</span> <strong>OHLCV Table:</strong> 547K+ rows, 501 tickers, 5-year span
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-mint-600 font-bold">→</span> <strong>Fundamentals:</strong> P/E, Market Cap, ROE, Sector, Analyst ratings
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-mint-600 font-bold">→</span> <strong>Events:</strong> Earnings dates, dividends, stock splits
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-mint-600 font-bold">→</span> Read-only schema optimized for analytics queries
                </li>
              </ul>
            </div>
            <div className="text-6xl">🗄️</div>
          </div>
          <div className="mt-4 p-4 bg-white/60 rounded-lg border border-mint-200">
            <code className="text-sm text-slate-700">
              <strong>File:</strong> data/market.duckdb<br/>
              <strong>Size:</strong> ~39 MB · Read-only mode in production
            </code>
          </div>
        </div>

        {/* Arrow */}
        <div className="flex justify-center">
          <div className="text-4xl text-slate-400">↓</div>
        </div>

        {/* Stage 3: API Layer */}
        <div className="bg-gradient-to-r from-lavender-50 to-lavender-100 rounded-xl p-8 border-2 border-lavender-400 shadow-lg">
          <div className="flex flex-col md:flex-row items-center gap-6">
            <div className="flex-1">
              <h3 className="text-2xl font-bold text-lavender-900 mb-3">🔌 Stage 3: FastAPI REST Layer</h3>
              <ul className="space-y-2 text-lavender-800">
                <li className="flex items-center gap-2">
                  <span className="text-lavender-600 font-bold">→</span> <strong>Dashboard API:</strong> Summary KPIs, health status
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-lavender-600 font-bold">→</span> <strong>Stocks API:</strong> Paginated list, detail inspection
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-lavender-600 font-bold">→</span> <strong>Analytics API:</strong> Signal coverage, feature quality
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-lavender-600 font-bold">→</span> <strong>Portfolio API:</strong> Live P/L, positions (from Breeze)
                </li>
              </ul>
            </div>
            <div className="text-6xl">⚡</div>
          </div>
          <div className="mt-4 p-4 bg-white/60 rounded-lg border border-lavender-200">
            <code className="text-sm text-slate-700">
              <strong>Service:</strong> services/ui-api (port 8010)<br/>
              <strong>Endpoints:</strong> /api/dashboard, /api/stocks, /api/analytics, /api/positions
            </code>
          </div>
        </div>

        {/* Arrow */}
        <div className="flex justify-center">
          <div className="text-4xl text-slate-400">↓</div>
        </div>

        {/* Stage 4: Frontend */}
        <div className="bg-gradient-to-r from-sky-50 to-blue-100 rounded-xl p-8 border-2 border-blue-400 shadow-lg">
          <div className="flex flex-col md:flex-row items-center gap-6">
            <div className="flex-1">
              <h3 className="text-2xl font-bold text-blue-900 mb-3">🎨 Stage 4: Next.js Dashboard</h3>
              <ul className="space-y-2 text-blue-800">
                <li className="flex items-center gap-2">
                  <span className="text-blue-600 font-bold">→</span> <strong>Overview Tab:</strong> KPI cards, health status, system metrics
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-blue-600 font-bold">→</span> <strong>Stocks Tab:</strong> Paginated table, technical filters, detail modal
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-blue-600 font-bold">→</span> <strong>Analysis Tab:</strong> Model performance, signal quality
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-blue-600 font-bold">→</span> <strong>Portfolio Tab:</strong> Live P/L, open positions, trade history
                </li>
              </ul>
            </div>
            <div className="text-6xl">🌐</div>
          </div>
          <div className="mt-4 p-4 bg-white/60 rounded-lg border border-blue-200">
            <code className="text-sm text-slate-700">
              <strong>Service:</strong> ui (port 3000)<br/>
              <strong>Stack:</strong> Next.js 15 · React 19 · TypeScript · Tailwind CSS
            </code>
          </div>
        </div>
      </div>

      {/* Data Flow Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mt-12">
        <div className="bg-gradient-to-br from-coral-100 to-coral-50 p-6 rounded-lg border-2 border-coral-300">
          <div className="text-4xl mb-2">📊</div>
          <h4 className="font-bold text-coral-900">Data Points</h4>
          <p className="text-2xl font-bold text-coral-600 mt-2">547K+</p>
          <p className="text-xs text-coral-700 mt-1">OHLCV rows indexed</p>
        </div>
        <div className="bg-gradient-to-br from-mint-100 to-mint-50 p-6 rounded-lg border-2 border-mint-400">
          <div className="text-4xl mb-2">🏷️</div>
          <h4 className="font-bold text-mint-900">Stock Universe</h4>
          <p className="text-2xl font-bold text-mint-600 mt-2">501</p>
          <p className="text-xs text-mint-700 mt-1">Nifty 500 tickers tracked</p>
        </div>
        <div className="bg-gradient-to-br from-lavender-100 to-lavender-50 p-6 rounded-lg border-2 border-lavender-400">
          <div className="text-4xl mb-2">⏱️</div>
          <h4 className="font-bold text-lavender-900">Sync Frequency</h4>
          <p className="text-2xl font-bold text-lavender-600 mt-2">Daily</p>
          <p className="text-xs text-lavender-700 mt-1">+ Live quotes in market hours</p>
        </div>
        <div className="bg-gradient-to-br from-sky-100 to-sky-50 p-6 rounded-lg border-2 border-sky-400">
          <div className="text-4xl mb-2">🔄</div>
          <h4 className="font-bold text-sky-900">Latency</h4>
          <p className="text-2xl font-bold text-sky-600 mt-2">&lt;100ms</p>
          <p className="text-xs text-sky-700 mt-1">API response time (P99)</p>
        </div>
      </div>

      {/* Technical Stack */}
      <div className="bg-gray-900 rounded-xl p-8 text-white mt-12">
        <h3 className="text-2xl font-bold mb-6">🛠️ Technical Stack</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div>
            <h4 className="font-bold text-emerald-400 mb-2">Data Sources</h4>
            <ul className="space-y-1 text-sm text-gray-300">
              <li>• yfinance (historical OHLCV)</li>
              <li>• ICICI Breeze API v2 (live quotes)</li>
              <li>• NSE live CSV (tickers)</li>
            </ul>
          </div>
          <div>
            <h4 className="font-bold text-violet-400 mb-2">Backend</h4>
            <ul className="space-y-1 text-sm text-gray-300">
              <li>• Python 3.13 + FastAPI</li>
              <li>• DuckDB (time-series)</li>
              <li>• Pandas 2.2.3</li>
            </ul>
          </div>
          <div>
            <h4 className="font-bold text-amber-400 mb-2">Frontend</h4>
            <ul className="space-y-1 text-sm text-gray-300">
              <li>• Next.js 15 + React 19</li>
              <li>• TypeScript</li>
              <li>• Tailwind CSS + Recharts</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Resume Capability */}
      <div className="bg-yellow-50 border-2 border-yellow-400 rounded-xl p-6">
        <h4 className="font-bold text-yellow-900 mb-2">⏸️ Resume Support</h4>
        <p className="text-sm text-yellow-800 mb-3">
          Pipeline maintains `.pipeline_state.json` tracking per-ticker progress. If interrupted, next run resumes from last checkpoint without re-downloading completed tickers.
        </p>
        <code className="text-xs bg-white p-3 rounded block text-slate-700">
          {'{'}
          "ticker": {'{'}
          "status": "completed",
          "updated": "2026-05-22",
          "rows": 1255,
          "error": null
          {'}'}
          {'}'}
        </code>
      </div>
    </div>
  )
}
