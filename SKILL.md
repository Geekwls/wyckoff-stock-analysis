---
name: wyckoff-stock-analysis
description: This skill should be used when the user asks to "analyze stock using Wyckoff", "Wyckoff analysis", "Wyckoff theory", "apply Wyckoff method", mentions "accumulation/distribution", "Wyckoff cycle", or discusses technical analysis using the Wyckoff method. Provides comprehensive stock market analysis based on Richard D. Wyckoff's proven methodology.
version: 2.0.0
---

## Data Sources

### Dual Data Source Strategy

| Market | Data Source | Reason |
|--------|------------|--------|
| A-Shares (China) | **Baostock** | Stable, no registration, designed for A-shares |
| US/HK/Other | **yfinance** | Wide coverage, global markets |

### Supported Input Formats

| Input | Example | Market |
|-------|---------|--------|
| Chinese name | `贵州茅台`, `比亚迪` | A-Shares |
| A-share code | `600519`, `002575` | A-Shares |
| A-share with suffix | `600519.SH`, `002575.SZ` | A-Shares |
| US stock | `AAPL`, `NVDA` | US |
| HK stock | `0700.HK` | HK |

### Cache Mechanism

Chinese stock names are cached locally (`stock_cache.json`) for faster subsequent lookups.

---

## Quick Reference

### Market Cycle Quick Guide
| Phase | Key Events | Volume Pattern | Trade Direction |
|-------|------------|----------------|-----------------|
| Accumulation | PS→CL→AR→ST→Spring→SOS→LPS | High→Low→High | Long |
| Distribution | PSY→CL→AR→ST→Upthrust→SOW→LPSY | High→Low→High | Short |

### Key Events Quick Guide
| Event | Full Name | Meaning | Trading Signal |
|-------|-----------|---------|----------------|
| PS | Preliminary Support | First buying after decline | Potential bottom |
| CL | Climax | Extreme price movement | Trend exhaustion |
| AR | Automatic Rally/Reaction | Quick rebound from CL | Counter-move |
| ST | Secondary Test | Re-test of CL | Supply/demand test |
| Spring | Spring | False breakdown below support | Buy signal (accumulation) |
| Upthrust | Upthrust | False breakout above resistance | Sell signal (distribution) |
| SOS | Sign of Strength | Strong breakout upward | Accumulation confirmed |
| SOW | Sign of Weakness | Strong breakdown downward | Distribution confirmed |
| LPS | Last Point of Support | Final pullback before markup | Best long entry |
| LPSY | Last Point of Supply | Final rally before markdown | Best short entry |

### Volume Standards Quick Guide
| Event | Volume Requirement | Duration | Confirmation |
|-------|-------------------|----------|--------------|
| CL | 3-5x average | - | Wide spread |
| Spring reversal | 1.5-2x breakdown | 1-3 days | Close above support |
| SOS/SOW | 1.5-2.5x average | 1-3 days | Close near high/low |
| LPS/LPSY | 40-60% of SOS/SOW | 1-5 days | Holds above/below key level |

### Trading Decision Quick Guide
```
1. Identify Phase → Accumulation/Distribution?
2. Wait for Spring/Upthrust → Confirmation
3. Wait for SOS/SOW → Breakout confirmation
4. Wait for LPS/LPSY → Pullback entry
5. Set Stop → Below Spring / Above Upthrust
6. Calculate R:R → Minimum 1.5:1
7. Execute Trade → With proper position sizing
```

---

# Wyckoff Stock Analysis

This skill applies Richard D. Wyckoff's proven technical analysis methodology to analyze stocks, identify market cycles, and make informed trading decisions based on supply and demand dynamics.

## Wyckoff Method Fundamentals

### Three Fundamental Laws

1. **The Law of Supply and Demand**
   - Price moves due to imbalance between supply (selling) and demand (buying)
   - When demand exceeds supply, prices rise; when supply exceeds demand, prices fall
   - Volume confirms the strength of price movements
   - Analyze volume-price relationships to identify institutional activity

2. **The Law of Cause and Effect**
   - Every significant price movement (effect) has a preceding cause
   - Trading ranges and accumulation/distribution patterns are the "cause"
   - The extent of the cause determines the magnitude of the effect
   - Larger accumulation/distribution phases lead to larger trends

3. **The Law of Effort vs. Result**
   - Compares price movement (result) with volume (effort)
   - Divergence indicates potential trend changes:
     - Price advances on low volume = weak demand (potential reversal)
     - Price declines on low volume = weak supply (potential support)
     - Price makes little progress on high volume = strong resistance/support

### Wyckoff's Five-Step Method (The Core Approach)

**Step 1: Determine the Present Position and Probable Future Trend**
- Identify the current phase: Accumulation, Markup, Distribution, or Markdown
- Analyze the broader market and sector context
- Compare individual stock behavior to market indices
- Use multiple timeframes (weekly > daily > hourly)
- Answer: "Where is this stock in the Wyckoff cycle?"

**Step 2: Determine the Relative Strength (RS)**
- Compare stock performance to the market index (e.g., S&P 500)
- Strong stock: Outperforms the market during uptrends, holds better during declines
- Weak stock: Underperforms the market, shows relative weakness
- RS Line: Plot stock price divided by index price to visualize strength
- Answer: "Is this stock stronger or weaker than the market?"

**Step 3: Identify Stocks That Are in Harmony with the Trend**
- During accumulation phase: Find stocks showing accumulation patterns
- During markup phase: Focus on stocks in Phase E (strong uptrend)
- During distribution phase: Look for stocks showing distribution
- During markdown phase: Focus on weak stocks to avoid or short
- Answer: "Is this stock's phase aligned with my trading strategy?"

**Step 4: Determine the Stock's Readiness to Move (Cause and Effect)**
- Measure the cause (trading range width in accumulation/distribution)
- Calculate potential effect using cause size
- Look for completion of Phase D (SOS/SOW confirmation)
- Assess volume patterns and spring/upthrust confirmation
- Answer: "How far is this stock likely to move based on its cause?"

**Step 5: Time Your Trades with Market Turns (Entry and Exit)**
- For longs: Enter on LPS after SOS confirmation in accumulation/reaccumulation
- For shorts: Enter on LPSY after SOW confirmation in distribution/redistribution
- Place stops logically: Below spring (longs) or above upthrust (shorts)
- Trail stops as the trend progresses in Phase E
- Exit when: Phase completes, volume diverges, or stops are hit
- Answer: "When is the optimal moment to enter and exit?"

**Practical Application of the 5 Steps**:

When analyzing any stock, systematically answer:
1. **Phase?** → Accumulation/Markup/Distribution/Markdown (A-E)
2. **Strength?** → Stronger/Weaker than market (RS analysis)
3. **Trend Harmony?** → Aligned with market direction or not
4. **Cause Size?** → Trading range = projected move
5. **Timing?** → Where is the optimal entry point?

## Wyckoff Market Cycle

### 1. Accumulation Phase (Institutional Buying)

**Phase A - Stopping the Downtrend**
- Preliminary Support (PS): First buying after decline, volume spikes
- Climactic Action (CL): Final panic selling, often with wide price spread and high volume
- Automatic Rally (AR): Quick rebound from CL, tests prior support
- Secondary Test (ST): Re-tests CL lows on lower volume, supply not fully absorbed

**Phase B - Building the Cause**
- Ranging price action as institutions accumulate
- Multiple secondary tests of support and resistance
- Volume decreases as supply is absorbed
- Signs of Strength (SOS) may appear

**Phase C - Shakeout & Positioning**
- Spring (or Shakeout): Price breaks support temporarily, shaking out weak holders
- False breakdown below AR quickly reverses
- Strong reversal with expanding volume
- Confirms smart money has absorbed all supply

**Phase D - Markup Begins**
- Sign of Strength (SOS): Strong breakout with increased volume
- Last Point of Support (LPS): Pullback to re-test breakout on lower volume
- Series of higher lows
- Demand clearly in control

**Phase E - Confirmation**
- Clear uptrend established
- Strong price advances on good volume
- Minor corrections are shallow and brief
- Path of least resistance is up

### 2. Markup Phase (Uptrend)
- Strong, persistent buying pressure
- Higher highs and higher lows
- Corrections are relatively mild
- Volume supports the upward movement
- Breakthroughs of resistance levels

### 3. Distribution Phase (Institutional Selling)

**Phase A - Stopping the Uptrend**
- Preliminary Supply (PSY): First significant selling after rally
- Climactic Action (CL): Final buying frenzy, often with excessive volume
- Automatic Reaction (AR): Quick decline from CL
- Secondary Test (ST): Re-tests CL highs on lower volume

**Phase B - Building the Cause**
- Ranging price action as institutions distribute
- Multiple tests of supply and demand levels
- Signs of Weakness (SOW) may appear
- Volume patterns change

**Phase C - Fake-Out & Positioning**
- Upthrust: Price breaks resistance temporarily, drawing in buyers
- False breakout above AR quickly reverses downward
- Strong reversal with expanding volume
- Confirms smart money has distributed

**Phase D - Markdown Begins**
- Sign of Weakness (SOW): Strong breakdown with increased volume
- Last Point of Supply (LPSY): Rally to re-test breakdown on lower volume
- Series of lower highs
- Supply clearly in control

**Phase E - Confirmation**
- Clear downtrend established
- Strong price declines on good volume
- Minor rallies are weak and brief
- Path of least resistance is down

### 4. Markdown Phase (Downtrend)
- Strong, persistent selling pressure
- Lower highs and lower lows
- Rallies are relatively weak
- Volume supports the downward movement
- Breakdowns of support levels

## Wyckoff Schematic Structures

### Accumulation Schematic (Reaccumulation)
- Key events: PS, CL, AR, ST, Spring, SOS, LPS, breakout
- Volume patterns: High on CL/AR/SOS, declining on ST/LPS
- Price spreads: Wide on reversal points, narrowing during ranging

### Distribution Schematic (Redistribution)
- Key events: PSY, CL, AR, ST, Upthrust, SOW, LPSY, breakdown
- Volume patterns: High on CL/AR/SOW, declining on ST/LPSY
- Price spreads: Wide on reversal points, narrowing during ranging

## Key Wyckoff Concepts

### Springs and Upthrusts

**Spring (Accumulation)**:
```
     Price
      │
Resistance ──────────────────────────────
      │
      │         ╭─╮
      │        ╱   ╲
      │       ╱     ╲
Support  ────╱───────╲─────────
      │    ╱          ╲
      │   ╱            ╲
      │  ╱              ╲
      │ ╱                ╲____
      │                      ↑ Reversal
      └──────────────────────────→ Time
           Spring
```
- **Spring**: Price briefly breaks below support then quickly reverses upward
  - Shakes out weak holders before markup
  - Often marks the beginning of Phase D
  - Should be accompanied by strong reversal volume

**Upthrust (Distribution)**:
```
     Price
      │
      │                      ╭─╮
      │                     ╱   ╲
      │                    ╱     ╲
Resistance ───────────────╱───────╲────
      │                  ╱         ╲
      │                 ╱           ╲
      │                ╱             ╲
Support  ───────────────────────────────
      │
      └──────────────────────────→ Time
                        Upthrust
```
- **Upthrust**: Price briefly breaks above resistance then quickly reverses downward
  - Draws in buyers before markdown
  - Often marks the beginning of Phase D in distribution
  - Should be accompanied by strong reversal volume

### Sign of Strength (SOS) / Sign of Weakness (SOW)
- **SOS**: Strong upward movement breaking resistance
  - Confirms transition from accumulation to markup
  - Must have expanding volume
  - Often followed by LPS retest

- **SOW**: Strong downward movement breaking support
  - Confirms transition from distribution to markdown
  - Must have expanding volume
  - Often followed by LPSY retest

### Last Point of Support (LPS) / Supply (LPSY)
- **LPS**: Final pullback before markup accelerates
  - Occurs after SOS
  - Volume declines compared to SOS
  - Excellent entry point for long positions

- **LPSY**: Final rally before markdown accelerates
  - Occurs after SOW
  - Volume declines compared to SOW
  - Excellent entry point for short positions

## Volume Analysis Guidelines

### Volume-Price Relationship Matrix
| Price | Volume | Interpretation | Market Implication |
|-------|--------|----------------|-------------------|
| Rising | Rising | Strong demand | Bullish continuation |
| Falling | Rising | Strong supply | Bearish continuation |
| Rising | Falling | Weak demand | Potential reversal (bearish) |
| Falling | Falling | Weak supply | Potential support (bullish) |

### Volume Patterns
| Pattern | Description | Significance |
|---------|-------------|--------------|
| Climactic Volume | Extremely high volume, often 3-5x average | Marks end of trend (Phase A), exhaustion of dominant force |
| Diminishing Volume | Declining volume during consolidation | Indicates absorption of supply/demand, precedes next move |
| Normal Volume | Average volume levels | Market in equilibrium, trend likely to continue |

## Support and Resistance Analysis

- **Support levels**: Price zones where buying pressure overcomes selling pressure
- **Resistance levels**: Price zones where selling pressure overcomes buying pressure
- **Role reversal**: Broken support becomes resistance; broken resistance becomes support
- **Wyckoff focuses on zones, not exact price points**

## Quantitative Trading Standards (Volume, Price, and Time)

### Volume Confirmation Standards

**Preliminary Support (PS) / Preliminary Supply (PSY)**:
- Volume: **1.5-3x average daily volume**
- Spread: Wide price spread (high volatility)
- After: Price should stabilize and begin ranging

**Climax (CL)**:
- Volume: **3-5x+ average daily volume** (extreme spike)
- Spread: Very wide price spread
- Location: End of a trend (markup or markdown)
- After: Automatic Rally (AR) or Automatic Reaction follows

**Automatic Rally (AR) / Automatic Reaction**:
- Volume: **High, but less than CL volume** (typically 2-3x average)
- Duration: **1-3 days** for the initial move
- After: Secondary Test (ST) follows

**Secondary Test (ST)**:
- Volume: **Declining** (typically 50-70% of CL/AR volume)
- Duration: **1-5 days**
- Price: Should NOT exceed the CL extreme significantly
- Multiple STs: Each successive ST shows lower volume

**Spring (Accumulation)**:
- Time breakdown: **1-3 days below support**
- Volume on breakdown: Moderate to high (weak holders panic)
- Volume on reversal: **Expanding** (1.5-2x breakdown volume)
- Recovery: Price must move back **above the broken support level**
- Confirmation: Close above support within 1-3 days
- **Failed Spring**: Price closes below support for **3+ days** → do NOT enter longs

**Upthrust (Distribution)**:
- Time breakout: **1-3 days above resistance**
- Volume on breakout: High (draws in buyers)
- Volume on rejection: **Expanding** (1.5-2x breakout volume)
- Rejection: Price must move back **below the broken resistance level**
- Confirmation: Close below resistance within 1-3 days
- **Failed Upthrust**: Price closes above resistance for **3+ days** → distribution may have failed

**Sign of Strength (SOS)**:
- Volume: **1.5-2.5x average daily volume**
- Price gain: **3-7%+ move** breaking resistance
- Spread: Wide spread upward
- Confirmation: **Close near the high of the day** (not just intraday spike)
- After: LPS pullback follows (volume should decline)

**Sign of Weakness (SOW)**:
- Volume: **1.5-2.5x average daily volume**
- Price decline: **3-7%+ drop** breaking support
- Spread: Wide spread downward
- Confirmation: **Close near the low of the day** (not just intraday dip)
- After: LPSY rally follows (volume should decline)

**Last Point of Support (LPS)**:
- Volume: **Declining** (typically 40-60% of SOS volume)
- Price: Pullback of **2-5%** from SOS highs
- Duration: **1-5 days**
- Hold: Price should hold **above recent swing lows**
- Entry: Best long entry point in accumulation

**Last Point of Supply (LPSY)**:
- Volume: **Declining** (typically 40-60% of SOW volume)
- Price: Rally of **2-5%** from SOW lows
- Duration: **1-5 days**
- Hold: Price should stay **below recent swing highs**
- Entry: Best short entry point in distribution

### Price and Time Standards

**Trading Range Duration (Phase B)**:
- Major accumulation/distribution: **8-20 weeks** (typical)
- Re-accumulation/re-distribution: **3-8 weeks** (shorter)
- Volume: Generally declining overall as absorption completes

**Phase A (Stopping the Trend)**:
- Duration: **1-4 weeks**
- Events: PS/PSY → CL → AR → ST sequence
- Volume: Very high on CL and AR

**Phase C (Shakeout)**:
- Spring/Upthrust duration: **1-5 days** total
- Quick reversal required (1-3 days back inside range)
- Volume expansion on reversal is critical

**Phase D (Sign of Movement)**:
- SOS/SOW confirmation: **1-3 days** for the breakout move
- LPS/LPSY follows: **1-5 days** later
- This is the primary entry zone

**Phase E (Confirmation)**:
- Trend accelerates: **3-10+ weeks** of directional movement
- Volume: Should support the trend (no major divergences)
- Corrections: Shallow and brief (1-3 days)

### Stop Loss Placement Standards

**For Long Positions (after LPS)**:
- Conservative stop: **Below the Spring low**
- Moderate stop: **2-3% below entry price**
- Aggressive stop: **Below the most recent swing low**
- Trail stop: As Phase E progresses, trail below higher lows

**For Short Positions (after LPSY)**:
- Conservative stop: **Above the Upthrust high**
- Moderate stop: **2-3% above entry price**
- Aggressive stop: **Above the most recent swing high**
- Trail stop: As markdown progresses, trail above lower highs

### Position Sizing Standards

**Phase A-B entries (early, risky)**:
- Position size: **25-35% of normal**
- Reason: High risk of pattern failure

**Phase D entries (primary entry zone)**:
- Position size: **75-100% of normal**
- Reason: Best risk/reward after SOS/SOW + LPS/LPSY

**Phase E entries (trend following)**:
- Position size: **50-75% of normal**
- Reason: Trend is established but move is partially complete

**Re-accumulation/Re-distribution**:
- Position size: **50-75% of normal**
- Reason: Shorter duration, smaller cause = smaller effect

### Risk/Reward Standards

**Minimum acceptable R:R ratio**: **1.5:1**
- Ideal: **2:1 to 3:1**

**Calculation using Cause and Effect**:
```
Risk = Entry Price - Stop Loss Price
Target = Breakout Price ± Cause Size
Reward = |Target - Entry Price|
R:R Ratio = Reward / Risk

Example (Accumulation):
- Trading Range: $40 - $50 (Cause = $10)
- Breakout: $51
- Entry (LPS): $49
- Stop: $47 (below Spring)
- Target: $51 + $10 = $61
- Risk: $49 - $47 = $2
- Reward: $61 - $49 = $12
- R:R Ratio: $12 / $2 = 6:1 (Excellent)
```

**If R:R < 1.5:1**: Skip the trade or wait for better entry

### Time-Based Exit Standards

**If Phase E doesn't develop within expected timeframe**:
- Accumulation → Markup: SOS should trigger sustained move within **1-2 weeks**
- Distribution → Markdown: SOW should trigger sustained decline within **1-2 weeks**
- If trend doesn't develop: Exit at breakeven or small loss

**Maximum holding periods**:
- Swing trades: **3-8 weeks** (typical Phase E duration)
- Position trades: **2-6 months** (larger cycle)
- If target not reached within timeframe: Reassess

### Volume Divergence Warning Signals

**Warning signs during trend**:
- Price makes new high on **lower volume** → divergence
- Price makes little progress on **very high volume** → absorption/resistance
- Multiple divergences in succession → trend weakening

**Action on divergence**:
- Reduce position size by 25-50%
- Tighten stop loss
- Be prepared to exit entirely
- Look for Phase A signs (PSY/PS, CL)

### Confirmation Standards (Multiple Timeframes)

**Always confirm across 2-3 timeframes**:
- Primary analysis: Daily chart (patterns and phases)
- Trend confirmation: Weekly chart (overall direction)
- Entry timing: Hourly chart (precise LPS/LPSY)
- **Conflict rule**: If timeframes conflict, wait or skip the trade

## Advanced Wyckoff Concepts

### Wyckoff Wave
The Wyckoff Wave is a market index created by Wyckoff to represent the overall market structure.
- **Purpose**: Provides a baseline for individual stock comparison
- **Modern equivalent**: Use broad market indices (S&P 500, NASDAQ, Shanghai Composite)
- **Application**:
  - Compare individual stock performance to the index
  - Gauge overall market health (bullish or bearish)
  - Identify market-wide accumulation or distribution phases
- **Key insight**: Strong stocks should outperform during accumulation/markup; weak stocks underperform during distribution/markdown

### Trading Range Sub-Structures

**Within any trading range (accumulation or distribution), identify these zones**:

1. **Trading Range (TR)**
   - The horizontal price zone between support and resistance
   - Where accumulation or distribution occurs
   - Can last weeks to months

2. **The Creek (Support Line)**
   - In accumulation: The lower boundary (support)
   - In distribution: The upper boundary (resistance)
   - Price often returns to test this level

3. **The Ice Line (Resistance Line in Accumulation)**
   - The upper boundary of an accumulation trading range
   - Strong resistance until broken by SOS
   - Often becomes support after breakout (role reversal)

### Optimism Position vs Danger Position

**Optimism Position**:
- **In Accumulation**: Near the top of the range, before the final markup
- **Characteristics**: Bulls become optimistic, but smart money is still cautious
- **Trading implication**: Be careful entering longs here; wait for LPS

**Danger Position**:
- **In Distribution**: Near the bottom of the range, before markdown
- **Characteristics**: Bears are confident, bulls are trapped
- **Trading implication**: Avoid longs entirely; consider shorts on LPSY

### Creeping Trends
A "creeping" trend is a gradual, almost imperceptible movement in price:
- **Creeping Up**: Slow, steady rise within a trading range
  - Often indicates accumulation before markup
  - Smart money is quietly buying

- **Creeping Down**: Slow, steady decline within a trading range
  - Often indicates distribution before markdown
  - Smart money is quietly exiting

**Key insight**: Creeping trends are hard to spot in real-time but reveal themselves on longer timeframes. They confirm Phase B activity.

### Stop Volume
- **Definition**: Extremely high volume that stops the price movement
- **In accumulation**: Stops the decline, often marks the climax (CL)
- **In distribution**: Stops the advance, often marks the climax
- **Characteristics**:
  - Volume spike 2-3x normal levels
  - Wide price spread
  - Followed by a trading range

### Spring Variations

**Classic Spring**:
- Price breaks support, quickly reverses
- Volume increases on breakdown, expands further on reversal
- Confirms smart money has absorbed all supply

**Failed Spring (Spring Failure)**:
- Price breaks support and does NOT quickly recover
- Indicates distribution is still active or accumulation failed
- Do NOT enter long positions
- Often leads to further decline

**Spring Test (Back-up to Spring)**:
- After a successful spring and SOS, price returns to test the spring lows
- Volume should be significantly lower
- Provides a second chance entry (another LPS)

### Upthrust Variations

**Classic Upthrust**:
- Price breaks above resistance, quickly reverses downward
- Smart money uses this to distribute remaining shares
- Confirms the start of markdown

**Failed Upthrust**:
- Price breaks resistance and keeps going
- Indicates strong demand; distribution may have failed
- Can lead to continued markup (re-accumulation)
- Be flexible and reassess

**Upthrust After Distribution**:
- Most common upthrust pattern
- Occurs after a clear distribution phase
- High volume on the breakout attempt
- Quick and decisive rejection

### Absorption Patterns

**Supply Absorption** (in accumulation):
- Repeated tests of support with decreasing volume
- Spring eliminates remaining weak holders
- Smart money buys all available supply
- Leads to markup

**Demand Absorption** (in distribution):
- Repeated tests of resistance with decreasing volume
- Upthrust absorbs remaining buying interest
- Smart money sells into all demand
- Leads to markdown

### Secondary Test (ST) Variations

**ST #1, ST #2, ST #3...**:
- A trading range can have multiple secondary tests
- Each subsequent test typically shows lower volume
- Final ST shows minimal volume = absorption complete
- Spring/upthrust usually follows the final ST

### Re-Accumulation vs Re-Distribution

**Re-Accumulation**:
- Occurs during an ongoing uptrend (Phase E of larger cycle)
- Shorter duration than major accumulation (3-6 weeks)
- Shallow trading range relative to the uptrend
- Pattern: LPS after SOS → continuation of uptrend
- Trading approach: Enter longs on LPS, tight stops below range

**Re-Distribution**:
- Occurs during an ongoing downtrend (Phase E of larger cycle)
- Shorter duration than major distribution (3-6 weeks)
- Shallow trading range relative to the downtrend
- Pattern: LPSY after SOW → continuation of downtrend
- Trading approach: Enter shorts on LPSY, tight stops above range

### Composite Man Psychology

**Understanding the "Smart Money" Mindset**:
- **In accumulation**: Quiet accumulation, avoiding attention
- **At climax**: Letting emotions run, creating the final flush
- **In distribution**: Hype and optimism, selling into strength
- **After spring/upthrust**: Ruthless exploitation of weak hands

**Your goal**: Align with the Composite Man, not fight against him. Ask: "What would the smartest, best-informed trader do right now?"

## Trend Analysis

1. **Identify the current phase**: Accumulation, Markup, Distribution, or Markdown
2. **Analyze volume patterns**: Confirm or diverge from price action
3. **Locate key levels**: PS/CL, AR, ST, Spring/Upthrust, SOS/SOW, LPS/LPSY
4. **Determine position of the Composite Man**: What would smart money do?
5. **Plan trade entries/exits**: Based on phase completion and confirmation

## Trading Applications

### Identifying Accumulation
- Look for long trading ranges after a decline
- Find PS, CL, AR, ST sequence
- Watch for Spring or test of support
- Confirm with SOS breakout
- Enter on LPS

### Identifying Distribution
- Look for long trading ranges after an advance
- Find PSY, CL, AR, ST sequence
- Watch for Upthrust or test of resistance
- Confirm with SOW breakdown
- Enter on LPSY (short)

### Position Sizing
- Larger positions in Phase D entries (LPS/LPSY)
- Smaller positions in early phases (A-B)
- Pyramid positions as trend confirms in Phase E

### Risk Management
- Place stops below Spring (for longs) or above Upthrust (for shorts)
- Risk-reward ratio should favor the potential move based cause size
- Exit if volume-price relationships don't confirm expectations

## Decision Flowcharts

### Phase Identification Decision Tree
```
Start
  ↓
Is there sideways movement after a decline?
  ├─ Yes → Possible Accumulation
  │     ↓
  │   Is there PS→CL→AR→ST sequence?
  │     ├─ Yes → Confirm Accumulation
  │     └─ No → Wait for more signals
  └─ No → Check if sideways after rally
        ├─ Yes → Possible Distribution
        └─ No → Check current trend
              ├─ Strong uptrend → Markup (wait for distribution signs)
              └─ Strong downtrend → Markdown (wait for accumulation signs)
```

### Trading Decision Flowchart
```
Identify Spring/Upthrust
  ↓
Wait for SOS/SOW confirmation
  ↓
Wait for LPS/LPSY pullback
  ↓
Is volume declining on pullback?
  ├─ Yes → Entry signal
  └─ No → Wait or skip
  ↓
Set stop loss (below Spring / above Upthrust)
  ↓
Calculate Risk:Reward ratio
  ├─ >1.5:1 → Execute trade
  └─ <1.5:1 → Skip or wait for better entry
```

### Risk Management Flowchart
```
Before Trade:
  ├─ Is pattern clear? → No → Skip trade
  ├─ Is R:R > 1.5:1? → No → Skip trade
  ├─ Is position size < 2% risk? → No → Reduce size
  └─ Is stop loss logical? → No → Recalculate

During Trade:
  ├─ Price hits stop → Exit immediately
  ├─ Volume diverges → Tighten stop
  ├─ Target reached → Take profit
  └─ Phase completes → Exit

After Trade:
  ├─ Win → Record lessons learned
  ├─ Loss → Analyze what went wrong
  └─ Breakeven → Review entry timing
```

## Analysis Checklist

When analyzing a stock using the Wyckoff Method:

1. **Current Trend Direction**: Up, Down, or Sideways?
2. **Volume Confirmation**: Does volume support the price action?
3. **Phase Identification**: Which Wyckoff phase is the stock in?
4. **Key Levels**: Where are support/resistance zones?
5. **Cause Size**: How large is the accumulation/distribution pattern?
6. **Spring/Upthrust**: Any shakeout patterns visible?
7. **SOS/SOW**: Has a sign of strength/weakness occurred?
8. **LPS/LPSY**: Is there a safe entry point?
9. **Effort vs Result**: Any divergences between price and volume?
10. **Composite Man Position**: What would institutional traders do?

## Important Notes

- **No single pattern guarantees success**: Always use multiple confirmations
- **Context matters**: Consider overall market conditions and sector trends
- **Timeframes**: Apply analysis across multiple timeframes for confirmation
- **Practice**: Wyckoff analysis requires significant practice and experience
- **Patience**: Wait for clear confirmations before entering trades
- **Flexibility**: Be prepared to reassess if new information emerges

Remember: The Wyckoff Method is about understanding the behavior of institutional traders (the "Composite Man") and positioning yourself to benefit from their actions. Focus on identifying where smart money is accumulating or distributing, and trade in harmony with their activities.
