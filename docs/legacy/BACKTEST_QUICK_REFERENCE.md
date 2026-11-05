# Backtest Lab — Quick Reference Card

## 🎯 Filter Quick Guide

| Filter | Type | Typical Range | Example | Interpretation |
|--------|------|----------------|---------|-----------------|
| P/E Ratio | `< number` | 15-30 | `< 25` | Cheap valuation |
| Dividend Yield | `> number %` | 1-4 | `> 1.5%` | Income filter |
| Market Cap | `> number Cr` | 500-5000 | `> 500` | Liquidity filter |
| ROCE % | `> number %` | 10-20 | `> 15%` | Quality filter |
| Price > MA50 | Toggle | ON/OFF | ON | Short-term uptrend |
| Price > MA200 | Toggle | ON/OFF | ON | Long-term uptrend |
| MA50 > MA200 | Toggle | ON/OFF | ON | Golden cross |
| RSI (14) | `> number` | 20-40 | `> 30` | Not oversold |
| ATR % (14) | `< number %` | 2-6 | `< 5%` | Low volatility |
| Above 52W Low | `> number %` | 20-40 | `> 30%` | Recovery signal |
| Within 52W High | `< number %` | 10-30 | `< 25%` | Pullback zone |
| Distance MA200 | `< number %` | 10-20 | `< 20%` | Not extended |
| Volume > Avg | Toggle | ON/OFF | ON | High conviction |

---

## 🚀 5 Pre-Built Strategies

### 1. BLUE CHIP VALUE
```
✓ P/E < 25
✓ ROCE > 15%
✓ Market Cap > ₹1000 Cr
✓ Price > 200-day MA

Expected: 50-55% win, +1% avg return
Best for: Conservative investors
```

### 2. DIVIDEND INCOME
```
✓ Dividend Yield > 2%
✓ ROCE > 12%
✓ Price > 50-day MA
✓ Market Cap > ₹500 Cr

Expected: 52-58% win, +0.8% avg return
Best for: Income-focused traders
```

### 3. TREND FOLLOWING
```
✓ Price > 50-day MA
✓ 50-day MA > 200-day MA
✓ Volume > 20-day Avg
✓ RSI > 30

Expected: 48-52% win, +0.9% avg return
Best for: Momentum traders
```

### 4. MEAN REVERSION
```
✓ Distance MA200 < -15%
✓ Above 52W Low > 15%
✓ ROCE > 10%
✓ ATR < 4%

Expected: 55-60% win, +0.6% avg return
Best for: Contrarian traders
```

### 5. AGGRESSIVE GROWTH
```
✓ P/E < 20
✓ ROCE > 20%
✓ Price > 200-day MA
✓ RSI > 40

Expected: 45-50% win, +1.5% avg return
Best for: Growth-focused traders
```

---

## 📊 Result Interpretation

### Win Rate
- **<45%** = Bad (skip this strategy)
- **45-50%** = OK (needs good returns per trade)
- **50-60%** = Good (professional level)
- **>60%** = Excellent (rare, validate carefully)

### Avg Return Per Trade
- **<0%** = Losing strategy (STOP)
- **0-0.5%** = Marginal (after costs: break-even)
- **0.5-1.5%** = Good (typical institutional target)
- **>1.5%** = Excellent (validate for over-optimization)

### Sharpe Ratio
- **<0.2** = Lumpy, inconsistent results
- **0.2-0.5** = Acceptable
- **>0.5** = Good risk-adjusted returns

---

## ⚡ 30-Second Backtest Process

1. **Set dates**: Pick "6M" button (6-month window)
2. **Add filters**: Check 3-4 boxes from one strategy above
3. **Run**: Click "▶ Run Backtest" button
4. **Check results**: Look at Win Rate %, Avg Return %
5. **Decide**: If 50%+ win rate → good; else remove a filter & retry

---

## 🎲 Filter Combinations That Work

### Safe Combo (Low Risk)
- P/E < 25
- ROCE > 15%
- Price > 200-day MA
→ Result: Stable 50-55% win, 0.8-1.2% return

### Balanced Combo (Medium Risk)
- P/E < 30
- ROCE > 12%
- Volume > Avg
→ Result: 52-58% win, 1.0-1.5% return

### Aggressive Combo (High Risk)
- P/E < 20
- ROCE > 20%
- Distance MA200 < 10% (tight range)
→ Result: 45-55% win, 1.5-2.5% return (if works)

---

## ⚠️ Red Flags

| Red Flag | What It Means | Action |
|----------|---------------|--------|
| Win rate < 45% | Strategy losing | Abandon filter combo |
| 0 trades generated | Filters too strict | Remove 1-2 filters |
| Equity curve down | Losses piling up | Wrong market regime |
| Sharpe < 0.2 | Very erratic | Add volatility/quality filter |
| All wins in one month | Over-optimized | Test on new time period |

---

## 🔍 Validation Tests

Before trusting a backtest:

```
✓ Test on 6+ months of data (not 1 month)
✓ Check on DIFFERENT time period (2023, 2022, 2021)
✓ Win rate should be consistent across periods
✓ Sharpe ratio > 0.3
✓ No extreme drawdowns (>-20%)
```

---

## 📱 Settings Cheat Sheet

| Setting | For Short Trades | For Long Holds |
|---------|------------------|-----------------|
| Forward Days | 3-5 | 10-15 |
| Date Range | 3-6 months | 12-24 months |
| Win Threshold | 0% | +0.5% |
| Max Stocks/Day | 20-50 | 50+ |

---

## 💡 Pro Tips

1. **Start with 6M date range**, not 5 years
2. **Aim for 50-55% win rate**, not 80%+
3. **Test different time periods** to prove robustness
4. **Simpler is better**: 3 filters > 10 filters
5. **High Sharpe matters more than high win rate**

---

## 🚨 Common Pitfalls

```
❌ Testing 1 month of data (too small)
❌ Using 15+ filters (overfitting)
❌ Expecting >2% returns/trade (unrealistic)
❌ Not validating on other time periods
❌ Ignoring transaction costs

✅ Test 6+ months
✅ Use 3-5 filters
✅ Target 0.5-1.5% returns
✅ Always validate period-by-period
✅ Assume 0.05% slippage per trade
```

---

## 📞 Quick Help

**Q: How many filters should I use?**  
A: 3-5 is ideal. More = overfitting.

**Q: What's a good win rate?**  
A: 50-60% is institutional standard. 45%+ with good returns is acceptable.

**Q: Should I trade what the backtest says?**  
A: NO. Backtest is **validation only**. Always paper trade first.

**Q: Why do my 2024 filters fail in 2023?**  
A: **Look-ahead bias**. Markets change. Test multiple periods.

**Q: Can I use these filters live?**  
A: Yes, but start with paper trading → small ₹1000 position → scale up.

---

**Version**: 1.0  
**Last Updated**: May 23, 2026  
**Status**: ✅ Ready to Use
