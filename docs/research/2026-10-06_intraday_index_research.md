# What it takes to win at Nifty / Bank Nifty intraday: public research, and what it means for U2

*Desk research, 2026-10-06. Sources are at the end. These are **ideas to test live in U2**, not proven rules for our market.*

## 1. Starting point: who wins, and why

| Fact | Source |
|---|---|
| **~91% of individual F&O traders lost money in FY25.** Net losses widened 41% to **₹1,05,603 crore** (after costs). The FY24 picture was similar. | SEBI study, Jul 2025 |
| 93% of over 1 crore individual traders lost money over FY22–FY24 (≈ ₹1.81 lakh crore in total). | SEBI study, Sep 2024 |
| The profits go to **proprietary traders (≈ ₹33,000 cr gross in FY24) and FPIs (≈ ₹28,000 cr)**. **97% of FPI and 96% of proprietary profits came from algorithmic trading.** | SEBI study, Sep 2024 |

**What the winners have that retail doesn't:**
- **speed**: they react to order flow in milliseconds;
- **liquidity provision**: they earn the spread instead of paying it;
- **option selling at scale**: they collect the volatility premium;
- **lower costs**.

So a retail-speed intraday option *buyer* starts behind. A winning approach has to rely on effects that **last minutes to hours** (where speed matters less) and must clear **costs plus the volatility premium**.

## 2. What research says about intraday index behaviour

### 2.1 Short horizons (seconds to minutes): price tends to bounce back
- Large studies of US index futures find **statistically significant intraday price reversals**. The effect **fades monotonically and is gone within about 4 hours**, consistent with microstructure: bid–ask bounce, dealer inventory, order-flow imbalance.
- The reversals are **strongest at the open after a large overnight gap**.
- Mean reversion appears across scales from minutes to days in frequently traded instruments.

**Matches our own live data (day 1, Q6):** on 6 Oct, most of our factors (momentum, order book, OI, heavyweights, and U2's health score itself) pointed the **wrong** way over the next 3 minutes. That's the "pendulum" we keep seeing. **Chasing 1–3 minute strength fights a documented effect.**

### 2.2 Longer horizons (30 min to the close): momentum
- **Market intraday momentum** (Gao, Han, Li, Zhou, *Journal of Financial Economics*): the **first half-hour's return predicts the last half-hour's return** (R² 1.6%, rising to 2.6% combined with the 12th half-hour). The prediction is **stronger on volatile, high-volume and macro-news days**.
- A simple timing strategy (trade the last half-hour in the direction of the first half-hour): about 6.7% a year, Sharpe about 1.1 (US ETF).
- **India:** a study of the Indian market finds **strong intraday momentum into the last half-hour**, linked to **hedging demand** (option dealers hedging their gamma).

### 2.3 Opening-range breakout: it works only on "in-play" days
- Zarattini, Barbon and Aziz (2016–2023, more than 7,000 US stocks): a **plain 5-minute ORB was weak**. Restricting it to **"stocks in play"** (unusually high opening volume, usually news-driven) did almost all the work.
- **For an index:** breakouts are worth taking mainly on **in-play days**: a large gap, news or an event, unusually high opening volume.

### 2.4 Order-flow imbalance (OFI) is the most robust short-horizon predictor
- Cont, Kukanov and Stoikov: over short intervals, price changes are **linear in the order-flow imbalance at the best bid/ask**, with impact **inversely proportional to book depth**. It's one of the most reproducible results in market microstructure, and a staple input for trading firms.
- It measures **changes in the queues at the best bid/ask**. That's different from "total buy qty ÷ total sell qty", which is what U2 v0.2 uses.

### 2.5 Dealer gamma and OI walls set the day's character
- **Positive dealer gamma** (dealers long options): dealers buy dips and sell rallies, so **low volatility, mean reversion and pinning** at heavy-OI strikes, especially on **expiry day**.
- **Negative gamma:** dealers hedge **with** the move, so **trends speed up**.
- Same-day-expiry options have gamma several times higher than weeklies, so pinning and squeezes are sharpest on expiry day (Nifty: Tuesday).

### 2.6 The volatility premium works against option buyers
- India: implied volatility (India VIX) is **above realised volatility on most days** (in one study, average VIX 16.6 vs realised 14.1). **Option buyers pay this premium every day**; sellers earn it.
- So an option *buyer* needs moves **larger than the option's implied move** just to break even before costs.
- The popular "9:20 short straddle" has a high win rate, but **average losses are 2–3× average wins**, and real results run about 15–30% worse than backtests (slippage, spreads, taxes). Option selling needs strict tail-risk control.

### 2.7 Time of day and the day's type
- Intraday volatility is **U-shaped**: highest in the first 30 minutes, lowest around midday, rising into the close. The first hour carries about 35–40% of the day's range.
- **Initial balance** (the first hour's range): a **trend day** typically extends to ≥ 2× the initial balance and closes in the top or bottom 25% of its range. Otherwise it's a **range day**. Breakout rules suit trend days; fade rules suit range days.

### 2.8 Meta-labeling (what U2's Gate 2 is)
- López de Prado: a primary model picks the **direction**; a secondary model decides **whether to act and how big**.
- **Precondition:** the primary signal must already have an edge. The secondary model can only **veto bad bets**; it can't create an edge. If U1's checklist has no edge, Gate 2 alone won't fix it.

## 3. Market structure changes that matter now (India)
- **From Nov 2024: one weekly expiry per exchange.** NSE kept only **Nifty 50** weeklies (now Tuesday). **Bank Nifty weekly options ended** (last on 13 Nov 2024), so Bank Nifty intraday options are **monthly only**: lower gamma, higher premium, a different behaviour from Nifty weeklies.
- **Larger lots** (minimum contract value ₹15–20 lakh; Nifty lot 65 in our data) and higher margins / extreme-loss margin on expiry day: sizing and risk per trade matter more.
- Participation fell sharply after these measures (individual traders: 61.4 lakh in Q1 FY25 → 42.7 lakh in Q4), which can change intraday flow patterns. **Live, recent data matters more than old history**, which supports the owner's live-first approach.

## 4. What a winning approach needs (synthesis)
1. **Trade the right horizon.** At **1–5 minutes, fade extremes** (reversion). For **30–60+ minutes, follow the day's direction** (momentum), especially on in-play or volatile days. Don't chase short-term strength.
2. **Classify the day first:** trend vs range (initial balance, opening relative volume, gap/news), plus the **dealer-gamma regime** (positive → fade toward OI walls; negative → follow breakouts).
3. **Use proper order flow:** OFI from the futures' best bid/ask queue changes, not total-quantity ratios.
4. **Respect the volatility premium:** buy options only when the **expected move exceeds the option's implied move plus costs**. Consider defined-risk selling only in a confirmed range or positive-gamma regime, with hard tail limits.
5. **Fewer, better trades.** Costs and the spread are certain; edges are small. Each trade should have a clear reason the market should move enough.
6. **Risk discipline:** a fixed risk per trade (≈ 1–2% of capital), a daily loss cap, no trading through scheduled events unless that's the strategy (U2 v0.2 NEWS already tests this).
7. **Evidence process:** forward/live testing, a small number of transparent rules, a decision on each rule from enough events, and **no tuning on a single day** (our scorecard rules already enforce this).

## 5. Proposals for U2 (for discussion; nothing built)

| # | Idea | Why (section) | What we'd have to add |
|---|---|---|---|
| **P1** | **Two modes:** *fade mode* (1–5 min extremes back toward VWAP/mean, range days) and *trend mode* (30–60 min holds on trend days) | 2.1, 2.2, 2.7 | a day-type classifier and a fade entry rule; the health score reused with the sign flipped for fades |
| **P2** | **A proper OFI factor** from futures best bid/ask changes (we already record 5-level depth) | 2.4 | a new factor in the health engine and the scorecard |
| **P3** | **A gamma-regime detector** from the option chain (strike OI × gamma → a net gamma proxy, the flip level, the main walls) | 2.5 | a calculation per chain snapshot; it decides fade vs trend mode |
| **P4** | **An "in-play day" filter** for breakouts: \|gap\| ≥ 0.5%, an event day, or opening volume ≥ 1.5× normal | 2.3 | uses the v0.2 morning card plus a relative-volume measure |
| **P5** | **An expected-move vs implied-move gate:** enter an option buy only if the setup's typical move (from the live scorecard) exceeds the option's implied move over the holding time plus costs | 2.6 | IV from the chain (already recorded) |
| **P6** | **Time-of-day regimes:** open (09:15–10:15), midday lull (11:30–13:30: no breakout entries), close (14:30–15:10) | 2.7 | a time filter as a shadow variant |
| **P7** | **A last-half-hour momentum shadow strategy:** at 14:45, trade in the direction of the first half-hour's return (stronger on volatile or news days); exit at 15:10 | 2.2 | a separate simple engine; one trade a day, easy to judge |
| **P8** | **Risk layer:** a daily loss cap and fixed risk per trade, for every U2 variant | 4.6 | shared rules |

**Suggested order** (most evidence, least effort): P7 and P2 first (simple, well-documented), then P3 and P1 (the biggest change: matching the trade horizon to the day's regime), then P4, P5, P6 and P8. Each goes in as a **shadow variant**, judged by the live scorecard, and enters MAIN only with the owner's approval.

## Sources
- SEBI, *Study on P&L of individual traders in equity derivatives, FY25* (Jul 2025): https://www.sebi.gov.in/sebi_data/attachdocs/jul-2025/1751900271726.pdf · Business Standard: https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html
- SEBI FY22–FY24 study coverage (prop/FPI profits, algo share): https://www.businesstoday.in/markets/story/93-of-individual-traders-incurred-losses-in-equity-fo-during-fy22-fy24-sebi-study-447102-2024-09-23 · https://pressinsider.com/news/fpis-tap-algos-to-snag-7-3-bn-in-profits-from-equity-derivatives/ · https://premium.capitalmind.in/2024/09/five-lessons-from-sebi-study/
- Gao, Han, Li, Zhou, *Market Intraday Momentum*, JFE: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866 · https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351 · APAC evidence: https://www.sciencedirect.com/science/article/pii/S0927538X2300152X
- *Hedging Demand and Intraday Momentum within the Indian Stock Market*: https://www.researchgate.net/publication/383567351_Hedging_Demand_and_Intraday_Momentum_within_the_Indian_Stock_Market
- Zarattini, Barbon, Aziz, *A Profitable Day Trading Strategy for the U.S. Equity Market* (ORB): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284 · summary of what the ORB papers found: https://danfin.net/opening-range-breakout-research
- Cont, Kukanov, Stoikov, *The Price Impact of Order Book Events*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1712822 · https://arxiv.org/pdf/1011.6402
- Intraday reversals in US index futures (15-year study): https://www.researchgate.net/publication/222520781_Intraday_price_reversals_in_the_US_stock_index_futures_market_A_15-year_study · *Trends and Reversion from Minutes to Decades*: https://arxiv.org/html/2501.16772v1 · noise reversals: https://www.cxoadvisory.com/fundamental-valuation/intraday-stock-returns-from-noise-reversals/
- Dealer gamma / pinning: https://flashalpha.com/articles/0dte-gamma-exposure-pin-risk-intraday-options-analytics · https://menthorq.com/guide/what-is-gamma-pinning/
- India volatility premium: https://github.com/RajolKumar2003/volatility-risk-premium-india · *Dynamics of variance risk premium: Evidence from India*: https://ideas.repec.org/a/eee/reveco/v70y2020icp321-334.html
- 9:20 straddle evidence and caveats: https://www.quintalmind.com/blog/time-based-straddle-strategy-nifty-options · https://www.marketcalls.in/futures-and-options/how-the-9-20-intraday-straddlers-are-being-gamed.html
- Initial balance / day types / U-shaped volatility: https://snpedge.vicitradingsolutions.com/p/the-initial-balance-strategy-how · https://volatilitybox.com/research/intraday-volatility-trading/
- Meta-labeling: https://en.wikipedia.org/wiki/Meta-Labeling · https://www.quantconnect.com/forum/discussion/14706/why-meta-labeling-is-not-a-silver-bullet/
- SEBI F&O measures (Nov 2024: weekly expiries, lot sizes): https://zerodha.com/z-connect/kite/a-short-brief-on-the-new-sebi-measures-for-the-fo-space · https://www.share.market/buzz/insights/sebi-fo-trading-regulations-2024-what-traders-need-to-know/
