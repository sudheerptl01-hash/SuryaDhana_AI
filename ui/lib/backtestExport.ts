/**
 * backtestExport.ts — compile a backtest result into downloadable artifacts.
 *
 * Excel path uses SheetJS, dynamically imported only on click so it never bloats
 * the initial bundle (keeps first paint fast / no layout shift). CSV path is
 * dependency-free and always works as a fallback.
 */
import type { BacktestResult } from './backtest'

function kpiRows(r: BacktestResult): (string | number)[][] {
  const c = r.config || ({} as any)
  return [
    ['Metric', 'Value'],
    ['Mode', r.mode],
    ['Scope', c.scope],
    ['Universe size', c.n_tickers],
    ['Benchmark', c.benchmark_label],
    ['Starting capital', r.starting_capital],
    ['Final NAV', r.final_nav],
    ['Total return %', r.total_return_pct],
    ['CAGR %', r.cagr_pct],
    ['Benchmark total return %', r.benchmark_total_return_pct],
    ['Alpha (annual) %', r.alpha_annual_pct],
    ['Beta', r.beta],
    ['Sharpe', r.sharpe_ratio],
    ['Sortino', r.sortino_ratio],
    ['Calmar', r.calmar_ratio],
    ['Max drawdown %', r.max_drawdown],
    ['Max DD duration (days)', r.max_drawdown_duration_days],
    ['Total trades', r.total_trades],
    ['Win rate %', r.win_rate],
    ['Avg win %', r.avg_win_return],
    ['Avg loss %', r.avg_loss_return],
    ['Win/Loss ratio', r.win_loss_ratio],
    ['Expectancy % / trade', r.expectancy],
    ['Profit factor', r.profit_factor],
    ['Exits — stop-loss', r.exit_breakdown?.stop_loss ?? 0],
    ['Exits — trailing', r.exit_breakdown?.trailing_stop ?? 0],
    ['Exits — time-stop', r.exit_breakdown?.time_stop ?? 0],
    ['Fundamental look-ahead active', String(r.fundamental_lookahead_active)],
  ]
}

function tradeRows(r: BacktestResult): (string | number)[][] {
  const header = ['Entry', 'Exit', 'Ticker', 'Sector', 'Entry Px', 'Exit Px', 'Gross %', 'Net %',
    'Hold (d)', 'Exit Reason', 'Capital', 'PnL', 'Win']
  const rows = r.trades.map(t => [
    t.entry_date, t.exit_date, t.ticker, t.sector || 'Unknown', t.entry_price, t.exit_price,
    t.gross_return_pct, t.return_pct, t.holding_days, t.exit_reason,
    t.capital_allocated, t.pnl, t.is_win ? 'WIN' : 'LOSS',
  ])
  return [header, ...rows]
}

function equityRows(r: BacktestResult): (string | number)[][] {
  const header = ['Date', 'NAV', 'Cash', 'Positions', 'Benchmark NAV', 'Drawdown %']
  const rows = r.equity_curve.map(e => [e.date, e.nav, e.cash, e.positions, e.benchmark_nav, e.drawdown_pct])
  return [header, ...rows]
}

function wfoRows(r: BacktestResult): (string | number)[][] {
  const header = ['Window Start', 'Window End', 'Trades', 'Avg %', 'Total %', 'Win %', 'Best %', 'Worst %']
  const rows = (r.wfo_windows || []).map(w => [w.start, w.end, w.trades, w.return_pct, w.total_return_pct, w.win_rate, w.best, w.worst])
  return [header, ...rows]
}

function toCSV(rows: (string | number)[][]): string {
  return rows.map(r => r.map(cell => {
    const s = String(cell ?? '')
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }).join(',')).join('\n')
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const stamp = () => new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')

/** Multi-section CSV (KPIs + trades + equity + WFO), dependency-free fallback. */
export function exportBacktestCSV(r: BacktestResult) {
  const sections: string[] = [
    '# SuryaDhana Backtest Lab — KPI Matrix', toCSV(kpiRows(r)),
    '', '# Trades', toCSV(tradeRows(r)),
    '', '# Equity Curve', toCSV(equityRows(r)),
  ]
  if (r.wfo_windows?.length) sections.push('', '# WFO Windows', toCSV(wfoRows(r)))
  download(new Blob([sections.join('\n')], { type: 'text/csv;charset=utf-8;' }),
    `backtest-${stamp()}.csv`)
}

/** Multi-tab .xlsx workbook via dynamically-imported SheetJS. */
export async function exportBacktestExcel(r: BacktestResult) {
  try {
    const XLSX = await import('xlsx')
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(kpiRows(r)), 'KPI Matrix')
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(tradeRows(r)), 'Trades')
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(equityRows(r)), 'Equity Curve')
    if (r.wfo_windows?.length) {
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(wfoRows(r)), 'WFO Windows')
    }
    XLSX.writeFile(wb, `backtest-${stamp()}.xlsx`)
  } catch {
    // SheetJS unavailable → graceful CSV fallback (never crash the cockpit).
    exportBacktestCSV(r)
  }
}
