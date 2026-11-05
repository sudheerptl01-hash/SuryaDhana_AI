'use client'

import { useState, useMemo } from 'react'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import clsx from 'clsx'

interface Trade {
  date: string
  ticker: string
  entry_price: number
  exit_price: number
  return_pct: number
  is_win: boolean
}

interface TradeExplorerProps {
  trades: Trade[]
  title?: string
  isDark?: boolean
  onTradeClick?: (trade: Trade) => void
  showHeader?: boolean
  showFooter?: boolean
}

type SortKey = 'date' | 'ticker' | 'return' | 'entry'
type SortOrder = 'asc' | 'desc'

export function TradeExplorer({ trades, title = 'Trade Explorer', isDark = true, onTradeClick, showHeader = true, showFooter = true }: TradeExplorerProps) {
  const [filterStartDate, setFilterStartDate] = useState<string>('')
  const [filterEndDate, setFilterEndDate] = useState<string>('')
  const [filterTicker, setFilterTicker] = useState<string>('')
  const [filterSectors, setFilterSectors] = useState<Set<string>>(new Set())
  const [selectedDates, setSelectedDates] = useState<Set<string>>(new Set())
  const [filterReturnMin, setFilterReturnMin] = useState<number>(-100)
  const [filterReturnMax, setFilterReturnMax] = useState<number>(100)
  const [filterWinOnly, setFilterWinOnly] = useState<boolean>(false)
  const [sortKey, setSortKey] = useState<SortKey>('date')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)
  const [expandedSectors, setExpandedSectors] = useState<Set<string>>(new Set())

  // Categorize trades by sector (using ticker prefixes as placeholder)
  const getSectorFromTicker = (ticker: string): string => {
    const sectors: Record<string, string> = {
      'RELIANCE': 'Energy',
      'TCS': 'IT',
      'INFY': 'IT',
      'WIPRO': 'IT',
      'HDFC': 'Banking',
      'ICICI': 'Banking',
      'AXIS': 'Banking',
      'LT': 'Infrastructure',
      'MARUTI': 'Auto',
      'SBIN': 'Banking',
      'ITC': 'FMCG',
      'NESTLEIND': 'FMCG',
      'HINDUSTAN': 'FMCG',
    }
    return sectors[ticker] || 'Other'
  }

  // Toggle date selection (multi-select)
  const toggleDate = (dateStr: string) => {
    if (!calendarData.has(dateStr)) return
    setSelectedDates(prev => {
      const next = new Set(prev)
      if (next.has(dateStr)) next.delete(dateStr)
      else next.add(dateStr)
      return next
    })
  }

  // Toggle sector filter (multi-select)
  const toggleSectorFilter = (sector: string) => {
    setFilterSectors(prev => {
      const next = new Set(prev)
      if (next.has(sector)) next.delete(sector)
      else next.add(sector)
      return next
    })
  }

  // Filter trades
  const filteredTrades = useMemo(() => {
    return trades.filter(trade => {
      const matchesDate = (!filterStartDate || trade.date >= filterStartDate) &&
                          (!filterEndDate || trade.date <= filterEndDate)
      const matchesSelectedDate = selectedDates.size === 0 || selectedDates.has(trade.date)
      const matchesTicker = !filterTicker || trade.ticker.includes(filterTicker.toUpperCase())
      const matchesReturn = trade.return_pct >= filterReturnMin && trade.return_pct <= filterReturnMax
      const matchesWin = !filterWinOnly || trade.is_win
      const sector = getSectorFromTicker(trade.ticker)
      const matchesSector = filterSectors.size === 0 || filterSectors.has(sector)

      return matchesDate && matchesSelectedDate && matchesTicker && matchesReturn && matchesWin && matchesSector
    })
  }, [trades, filterStartDate, filterEndDate, filterTicker, filterSectors, filterReturnMin, filterReturnMax, filterWinOnly, selectedDates])

  // Sort trades
  const sortedTrades = useMemo(() => {
    const sorted = [...filteredTrades].sort((a, b) => {
      let aVal: any = a[sortKey as keyof Trade]
      let bVal: any = b[sortKey as keyof Trade]

      if (sortKey === 'return') {
        aVal = a.return_pct
        bVal = b.return_pct
      } else if (sortKey === 'entry') {
        aVal = a.entry_price
        bVal = b.entry_price
      }

      const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0
      return sortOrder === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [filteredTrades, sortKey, sortOrder])

  // Group trades by sector (from all trades for global sector counts)
  const sectorGroups = useMemo(() => {
    const groups: Record<string, Trade[]> = {}
    trades.forEach(trade => {
      const sector = getSectorFromTicker(trade.ticker)
      if (!groups[sector]) groups[sector] = []
      groups[sector].push(trade)
    })
    return groups
  }, [trades])

  // Get unique sectors from filtered trades (for horizontal pills)
  const filteredSectors = useMemo(() => {
    const sectors = new Set<string>()
    filteredTrades.forEach(trade => {
      sectors.add(getSectorFromTicker(trade.ticker))
    })
    return Array.from(sectors).sort()
  }, [filteredTrades])

  // Calendar heatmap data
  const calendarData = useMemo(() => {
    const dateMap = new Map<string, { wins: number; losses: number; totalReturn: number }>()
    filteredTrades.forEach(trade => {
      const existing = dateMap.get(trade.date) || { wins: 0, losses: 0, totalReturn: 0 }
      dateMap.set(trade.date, {
        wins: existing.wins + (trade.is_win ? 1 : 0),
        losses: existing.losses + (trade.is_win ? 0 : 1),
        totalReturn: existing.totalReturn + trade.return_pct,
      })
    })
    return dateMap
  }, [filteredTrades])

  // Get unique dates for calendar
  const uniqueDates = Array.from(new Set(filteredTrades.map(t => t.date))).sort()
  const weeks = useMemo(() => {
    const result: string[][] = []
    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    if (uniqueDates.length === 0) return []

    const firstDate = new Date(uniqueDates[0])
    const lastDate = new Date(uniqueDates[uniqueDates.length - 1])
    const startDate = new Date(firstDate)
    startDate.setDate(startDate.getDate() - firstDate.getDay())

    const currentWeek: string[] = []
    const currentDate = new Date(startDate)

    while (currentDate <= lastDate) {
      const dateStr = currentDate.toISOString().split('T')[0]
      currentWeek.push(dateStr)

      if (currentDate.getDay() === 6) {
        result.push([...currentWeek])
        currentWeek.length = 0
      }
      currentDate.setDate(currentDate.getDate() + 1)
    }

    if (currentWeek.length > 0) result.push(currentWeek)
    return result
  }, [uniqueDates])

  const getHeatmapColor = (dateStr: string): string => {
    const data = calendarData.get(dateStr)
    if (!data) return 'bg-slate-800'
    const totalTrades = data.wins + data.losses
    if (totalTrades === 0) return 'bg-slate-800'
    const winRate = data.wins / totalTrades
    const avgReturn = data.totalReturn / totalTrades

    if (avgReturn > 2) return 'bg-emerald-700'
    if (avgReturn > 1) return 'bg-emerald-600'
    if (avgReturn > 0.5) return 'bg-emerald-500'
    if (avgReturn > 0) return 'bg-teal-600'
    if (avgReturn > -0.5) return 'bg-amber-600'
    if (avgReturn > -1) return 'bg-orange-600'
    return 'bg-rose-700'
  }

  const toggleSector = (sector: string) => {
    const next = new Set(expandedSectors)
    if (next.has(sector)) next.delete(sector)
    else next.add(sector)
    setExpandedSectors(next)
  }

  const bgGradient = isDark
    ? 'bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950'
    : 'bg-gradient-to-br from-slate-50 via-white to-slate-50'
  const textColor = isDark ? 'text-slate-100' : 'text-slate-900'
  const headerBg = isDark ? 'bg-slate-900/50 border-slate-700/50' : 'bg-slate-100/50 border-slate-300/50'
  const filterBg = isDark ? 'bg-slate-800/40 border-slate-700/50' : 'bg-white/40 border-slate-200/50'
  const filterText = isDark ? 'text-slate-400' : 'text-slate-600'
  const inputBg = isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-slate-200'
  const inputText = isDark ? 'text-slate-300' : 'text-slate-900'
  const accentColor = 'amber'

  return (
    <div className={clsx(bgGradient, textColor, 'font-mono')}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
        .font-ibm-mono { font-family: 'IBM Plex Mono', monospace; }
        input[type="range"] {
          -webkit-appearance: none;
          width: 100%;
          height: 4px;
          background: transparent;
          cursor: pointer;
        }
        input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 18px;
          height: 18px;
          background: #ffb000;
          cursor: pointer;
          border-radius: 50%;
          border: 2px solid ${isDark ? '#1a2130' : '#f1f5f9'};
          box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        input[type="range"]::-moz-range-thumb {
          width: 18px;
          height: 18px;
          background: #ffb000;
          cursor: pointer;
          border-radius: 50%;
          border: 2px solid ${isDark ? '#1a2130' : '#f1f5f9'};
          box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
      `}</style>

      {/* Header */}
      {showHeader && (
        <div className={clsx('border-b backdrop-blur-sm sticky top-0 z-30', headerBg)}>
          <div className="max-w-full px-6 py-5">
            <div className="flex items-baseline gap-3 mb-1">
              <h1 className={clsx('text-3xl font-bold tracking-tight font-ibm-mono',
                isDark ? 'bg-gradient-to-r from-amber-400 to-orange-500' : 'bg-gradient-to-r from-amber-600 to-orange-600',
                'bg-clip-text text-transparent'
              )}>
                ₹ TRADE EXPLORER
              </h1>
              <span className={clsx('text-xs font-light', filterText)}>v1.0 PREMIUM ANALYTICS</span>
            </div>
            <p className={filterText + ' text-sm'}>
              {filteredTrades.length} trades · {sortedTrades.filter(t => t.is_win).length} wins ·{' '}
              <span className={sortedTrades.length > 0 ? (sortedTrades.reduce((s, t) => s + t.return_pct, 0) > 0 ? 'text-emerald-400' : 'text-rose-400') : filterText}>
                {sortedTrades.length > 0 ? `${(sortedTrades.reduce((s, t) => s + t.return_pct, 0) / sortedTrades.length).toFixed(2)}%` : '—'} avg return
              </span>
            </p>
          </div>
        </div>
      )}

      <div className={clsx('max-w-full', showHeader && showFooter ? 'px-6 py-8' : showHeader ? 'px-6 py-8 pb-0' : showFooter ? 'px-6 py-0 pt-6' : 'px-6 py-0')}>
        <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-8">
          {/* Sidebar: Filters */}
          <div className="space-y-6">
            {/* Filter Panel */}
            <div className={clsx(filterBg, 'backdrop-blur rounded-lg p-4 space-y-4')}>
              <h3 className={clsx('text-xs uppercase tracking-widest font-bold font-ibm-mono',
                isDark ? 'text-amber-400' : 'text-amber-600'
              )}>Filters</h3>

              {/* Date Range */}
              <div className="space-y-2">
                <label className={clsx('text-xs', filterText)}>Date Range</label>
                <input
                  type="date"
                  value={filterStartDate}
                  onChange={e => setFilterStartDate(e.target.value)}
                  className={clsx(
                    'w-full rounded px-2 py-1 text-xs focus:outline-none transition-colors',
                    inputBg, inputText,
                    isDark ? 'focus:border-amber-500' : 'focus:border-amber-600'
                  )}
                  placeholder="Start"
                />
                <input
                  type="date"
                  value={filterEndDate}
                  onChange={e => setFilterEndDate(e.target.value)}
                  className={clsx(
                    'w-full rounded px-2 py-1 text-xs focus:outline-none transition-colors',
                    inputBg, inputText,
                    isDark ? 'focus:border-amber-500' : 'focus:border-amber-600'
                  )}
                  placeholder="End"
                />
              </div>

              {/* Ticker */}
              <div className="space-y-2">
                <label className={clsx('text-xs', filterText)}>Ticker</label>
                <input
                  type="text"
                  value={filterTicker}
                  onChange={e => setFilterTicker(e.target.value)}
                  placeholder="Search..."
                  className={clsx(
                    'w-full rounded px-2 py-1 text-xs focus:outline-none transition-colors',
                    inputBg, inputText,
                    isDark ? 'placeholder-slate-600 focus:border-amber-500' : 'placeholder-slate-400 focus:border-amber-600'
                  )}
                />
              </div>

              {/* Return Range Slider */}
              <div className="space-y-3">
                <label className={clsx('text-xs', filterText)}>Return Range</label>
                <div className="relative h-8 mt-4">
                  <div className={clsx('absolute top-3.5 h-1 rounded w-full', isDark ? 'bg-slate-700' : 'bg-slate-300')}/>
                  <div
                    className="absolute top-3.5 h-1 bg-amber-500 rounded"
                    style={{
                      left: `${((filterReturnMin + 100) / 200) * 100}%`,
                      right: `${100 - ((filterReturnMax + 100) / 200) * 100}%`,
                    }}
                  />
                  <input
                    type="range"
                    min={-100}
                    max={100}
                    value={filterReturnMin}
                    onChange={e => setFilterReturnMin(Math.min(parseInt(e.target.value), filterReturnMax - 1))}
                    className="absolute w-full appearance-none bg-transparent cursor-pointer z-10"
                  />
                  <input
                    type="range"
                    min={-100}
                    max={100}
                    value={filterReturnMax}
                    onChange={e => setFilterReturnMax(Math.max(parseInt(e.target.value), filterReturnMin + 1))}
                    className="absolute w-full appearance-none bg-transparent cursor-pointer z-20"
                  />
                </div>
                <div className="flex justify-between text-xs font-ibm-mono text-amber-400 mt-1">
                  <span>{filterReturnMin}%</span>
                  <span>{filterReturnMax}%</span>
                </div>
              </div>

              {/* Win Only */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filterWinOnly}
                  onChange={e => setFilterWinOnly(e.target.checked)}
                  className={clsx(
                    'w-4 h-4 rounded text-emerald-500',
                    isDark ? 'border-slate-600 bg-slate-900 focus:ring-emerald-500' : 'border-slate-400 bg-white focus:ring-emerald-600'
                  )}
                />
                <span className={clsx('text-xs', isDark ? 'text-slate-300' : 'text-slate-700')}>Winning Trades Only</span>
              </label>
            </div>

          </div>

          {/* Main Content */}
          <div className="space-y-6">
            {/* Calendar Heatmap */}
            {weeks.length > 0 && (
              <div className={clsx(filterBg, 'backdrop-blur rounded-lg p-6')}>
                <h3 className={clsx('text-xs uppercase tracking-widest font-bold font-ibm-mono mb-4',
                  isDark ? 'text-amber-400' : 'text-amber-600'
                )}>Trade Heatmap — Click to filter</h3>
                <div className="overflow-x-auto">
                  <div className="space-y-1 inline-block">
                    <div className="flex gap-1 mb-2">
                      {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map(d => (
                        <div key={d} className={clsx('w-7 h-7 text-[10px] flex items-center justify-center font-bold', filterText)}>
                          {d}
                        </div>
                      ))}
                    </div>
                    {weeks.map((week, i) => (
                      <div key={i} className="flex gap-1">
                        {week.map(dateStr => {
                          const data = calendarData.get(dateStr)
                          const isSelected = selectedDates.has(dateStr)
                          return (
                            <button
                              key={dateStr}
                              onClick={() => toggleDate(dateStr)}
                              title={data ? `${data.wins}W ${data.losses}L (${(data.totalReturn / (data.wins + data.losses)).toFixed(2)}%)` : 'No trades'}
                              className={clsx(
                                'w-7 h-7 rounded text-[8px] flex items-center justify-center cursor-pointer transition-all font-bold',
                                getHeatmapColor(dateStr),
                                data && data.wins + data.losses > 0 ? (isDark ? 'text-slate-100' : 'text-white') : (isDark ? 'text-slate-600' : 'text-slate-400'),
                                isSelected ? 'ring-2 ring-offset-1' : 'hover:ring-2 hover:ring-offset-1',
                                isSelected ? 'ring-amber-400 ring-offset-slate-900' : 'hover:ring-amber-400'
                              )}
                            >
                              {data && data.wins + data.losses > 0 ? data.wins + data.losses : ''}
                            </button>
                          )
                        })}
                      </div>
                    ))}
                  </div>
                </div>
                <div className={clsx('mt-4 flex items-center justify-between text-[10px]', filterText)}>
                  <span>Darker = Better Returns</span>
                  <div className="flex gap-1">
                    <div className="w-3 h-3 bg-emerald-700 rounded"></div>
                    <div className="w-3 h-3 bg-emerald-600 rounded"></div>
                    <div className="w-3 h-3 bg-emerald-500 rounded"></div>
                    <div className="w-3 h-3 bg-teal-600 rounded"></div>
                    <div className="w-3 h-3 bg-amber-600 rounded"></div>
                    <div className="w-3 h-3 bg-rose-700 rounded"></div>
                  </div>
                </div>
              </div>
            )}

            {/* Sector Filters (Horizontal Pills) */}
            {filteredSectors.length > 0 && (
              <div className={clsx(filterBg, 'backdrop-blur rounded-lg p-4')}>
                <div className="flex flex-wrap gap-2 items-center">
                  <span className={clsx('text-xs uppercase tracking-widest font-bold font-ibm-mono mr-2',
                    isDark ? 'text-amber-400' : 'text-amber-600'
                  )}>Sectors:</span>
                  {Object.entries(sectorGroups)
                    .sort((a, b) => b[1].length - a[1].length)
                    .map(([sector, sectorTrades]) => (
                      <button
                        key={sector}
                        onClick={() => toggleSectorFilter(sector)}
                        className={clsx(
                          'px-3 py-1.5 rounded-full text-xs font-semibold transition-all',
                          filterSectors.has(sector)
                            ? (isDark ? 'bg-amber-500/30 text-amber-300 ring-2 ring-amber-500/50' : 'bg-amber-200 text-amber-900 ring-2 ring-amber-400')
                            : (isDark ? 'bg-slate-700/50 text-slate-300 hover:bg-slate-700' : 'bg-slate-200 text-slate-700 hover:bg-slate-300')
                        )}
                      >
                        {sector} ({sectorTrades.length})
                      </button>
                    ))}
                </div>
              </div>
            )}

            {/* Trade List */}
            <div className={clsx(filterBg, 'backdrop-blur rounded-lg overflow-hidden')}>
              <div className={clsx(
                'border-b px-6 py-3 flex items-center justify-between',
                isDark ? 'border-slate-700/50 bg-slate-900/30' : 'border-slate-200/50 bg-slate-100/30'
              )}>
                <h3 className={clsx('text-xs uppercase tracking-widest font-bold font-ibm-mono',
                  isDark ? 'text-amber-400' : 'text-amber-600'
                )}>Trades ({sortedTrades.length})</h3>
                <div className="flex gap-2 text-[10px]">
                  {(['date', 'ticker', 'return', 'entry'] as const).map(key => (
                    <button
                      key={key}
                      onClick={() => {
                        if (sortKey === key) setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
                        else {
                          setSortKey(key)
                          setSortOrder('desc')
                        }
                      }}
                      className={clsx(
                        'px-2 py-1 rounded transition-all',
                        sortKey === key ? (isDark ? 'bg-amber-500/30 text-amber-300' : 'bg-amber-200 text-amber-900') : (isDark ? 'text-slate-500 hover:text-slate-400' : 'text-slate-600 hover:text-slate-700')
                      )}
                    >
                      {key === 'return' ? 'Return' : key === 'entry' ? 'Entry' : key === 'ticker' ? 'Stock' : 'Date'}
                      {sortKey === key && (sortOrder === 'asc' ? ' ↑' : ' ↓')}
                    </button>
                  ))}
                </div>
              </div>

              <div className={clsx(
                'max-h-[600px] overflow-y-auto',
                isDark ? 'divide-y divide-slate-700/30' : 'divide-y divide-slate-200/50'
              )}>
                {sortedTrades.length === 0 ? (
                  <div className={clsx('px-6 py-12 text-center text-sm', isDark ? 'text-slate-400' : 'text-slate-500')}>No trades match your filters</div>
                ) : (
                  sortedTrades.map((trade, idx) => (
                    <button
                      key={`${trade.date}-${trade.ticker}-${idx}`}
                      onClick={() => {
                        if (onTradeClick) {
                          onTradeClick(trade)
                        } else {
                          setSelectedTrade(selectedTrade?.date === trade.date && selectedTrade?.ticker === trade.ticker ? null : trade)
                        }
                      }}
                      className={clsx(
                        'w-full text-left px-6 py-3 transition-all border-l-4',
                        trade.is_win ? (isDark ? 'border-l-emerald-500 bg-emerald-500/5 hover:bg-emerald-500/10' : 'border-l-emerald-600 bg-emerald-50 hover:bg-emerald-100') : (isDark ? 'border-l-rose-500 bg-rose-500/5 hover:bg-rose-500/10' : 'border-l-rose-600 bg-rose-50 hover:bg-rose-100')
                      )}
                    >
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 mb-1">
                            <span className={clsx('font-bold text-sm font-ibm-mono', isDark ? 'text-amber-300' : 'text-amber-700')}>{trade.ticker}</span>
                            <span className={clsx('text-[10px]', isDark ? 'text-slate-500' : 'text-slate-600')}>{trade.date}</span>
                          </div>
                          <div className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-slate-600')}>
                            ₹{trade.entry_price.toFixed(0)} → ₹{trade.exit_price.toFixed(0)}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className={clsx('font-bold text-sm font-ibm-mono', trade.is_win ? 'text-emerald-400' : 'text-rose-400')}>
                            {fmtSigned(trade.return_pct, 2)}%
                          </div>
                          <div className={clsx('text-[10px]', isDark ? 'text-slate-500' : 'text-slate-600')}>{trade.is_win ? '✓ WIN' : '✗ LOSS'}</div>
                        </div>
                      </div>

                      {/* Expanded Details */}
                      {selectedTrade?.date === trade.date && selectedTrade?.ticker === trade.ticker && (
                        <div className={clsx('mt-3 pt-3 grid grid-cols-3 gap-3 text-xs',
                          isDark ? 'border-t border-slate-700/50' : 'border-t border-slate-200/50'
                        )}>
                          <div>
                            <div className={clsx('mb-1', isDark ? 'text-slate-500' : 'text-slate-600')}>Entry Price</div>
                            <div className={clsx('font-ibm-mono font-semibold', isDark ? 'text-amber-300' : 'text-amber-700')}>₹{trade.entry_price.toFixed(2)}</div>
                          </div>
                          <div>
                            <div className={clsx('mb-1', isDark ? 'text-slate-500' : 'text-slate-600')}>Exit Price</div>
                            <div className={clsx('font-ibm-mono font-semibold', isDark ? 'text-amber-300' : 'text-amber-700')}>₹{trade.exit_price.toFixed(2)}</div>
                          </div>
                          <div>
                            <div className={clsx('mb-1', isDark ? 'text-slate-500' : 'text-slate-600')}>Return</div>
                            <div className={clsx('font-ibm-mono font-bold', trade.is_win ? 'text-emerald-400' : 'text-rose-400')}>
                              {fmtSigned(trade.return_pct, 2)}%
                            </div>
                          </div>
                        </div>
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer Stats */}
      {showFooter && (
        <div className={clsx(
          'px-6 py-6',
          isDark ? 'border-t border-slate-700/50 bg-slate-900/30' : 'border-t border-slate-200/50 bg-slate-100/30',
          showHeader ? 'mt-12' : 'mt-0'
        )}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 text-sm">
            <div>
              <div className={clsx('text-xs uppercase tracking-wider mb-2 font-ibm-mono', isDark ? 'text-slate-500' : 'text-slate-600')}>Total Trades</div>
              <div className={clsx('text-2xl font-bold font-ibm-mono', isDark ? 'text-amber-300' : 'text-amber-700')}>{sortedTrades.length}</div>
            </div>
            <div>
              <div className={clsx('text-xs uppercase tracking-wider mb-2 font-ibm-mono', isDark ? 'text-slate-500' : 'text-slate-600')}>Win Rate</div>
              <div className="text-2xl font-bold font-ibm-mono text-emerald-400">
                {sortedTrades.length > 0 ? ((sortedTrades.filter(t => t.is_win).length / sortedTrades.length) * 100).toFixed(1) : 0}%
              </div>
            </div>
            <div>
              <div className={clsx('text-xs uppercase tracking-wider mb-2 font-ibm-mono', isDark ? 'text-slate-500' : 'text-slate-600')}>Avg Return</div>
              <div className={clsx('text-2xl font-bold font-ibm-mono', sortedTrades.length > 0 && sortedTrades.reduce((s, t) => s + t.return_pct, 0) / sortedTrades.length > 0 ? 'text-emerald-400' : 'text-rose-400')}>
                {sortedTrades.length > 0 ? `${(sortedTrades.reduce((s, t) => s + t.return_pct, 0) / sortedTrades.length).toFixed(2)}%` : '—'}
              </div>
            </div>
            <div>
              <div className={clsx('text-xs uppercase tracking-wider mb-2 font-ibm-mono', isDark ? 'text-slate-500' : 'text-slate-600')}>Total Return</div>
              <div className={clsx('text-2xl font-bold font-ibm-mono', sortedTrades.length > 0 && sortedTrades.reduce((s, t) => s + t.return_pct, 0) > 0 ? 'text-emerald-400' : 'text-rose-400')}>
                {sortedTrades.reduce((s, t) => s + t.return_pct, 0).toFixed(2)}%
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
