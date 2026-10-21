# Market & Options Desk

Local browser app that runs next to TWS. **Read-only:** it never places, modifies or
cancels orders (the TWS connection uses `readonly=True` and only market-data calls).

```
Start Options Desk.cmd      ->  http://127.0.0.1:8810
```

## Trade readiness

One size call for new premium selling, on every tab, from tested inputs only (VIX level and conditions since
1990, the five Market warnings since 2010, sector rotation since 1999), expressed as the chance SPX fell 5%+
within 21 sessions; the highest input sets the size, and A14 / calendar rules step individual structures down.
One VIX/VIX3M scale and two named trends (20-day short-term, 200-day long-term) are used throughout. A data
strip in the header shows each source's date against the last US close; missed recordings, final captures and
chains catch up when the laptop wakes. yfinance downloads run one at a time (concurrent downloads were
swapping rows between symbols).

## Tabs

| Tab | What it answers |
|---|---|
| **Today's pick** | VIX conditions panel (size for new premium selling and the active VIX/SPX/RUT/credit conditions with their history), then  Calendar (time spread) vs A14 put BWB (single expiry), SPX vs RUT: best setup in each from the same chain and odds, edge per day held, your own rules (VIX/VIX3M 0.834, TimeEdge/Triple/TimeZone gates, A14 trend), and one pick. |
| **Market** | The former claude.ai Market Desk, now local: regime, market warnings (Market Warnings v2 rules), breadth, volatility, sector rotation map, cross-asset ratios and Canary, US economic calendar, every TWS sub-account's balances and fills, and the STFS / BB+RSI watchlist. |
| **Today** | Where SPX vol term structure sits (VIX9D…VIX1Y), VIX/VIX3M with z-score, and pass/fail of the TimeEdge, Triple Calendar and TimeZone entry rules. |
| **Calendar scanner** | Every front/back expiry pair ranked by contango, contango z-score (maturity-matched), forward premium, or forward vol vs realized. Heatmap plus per-pair history: maturity-matched vs the actual expiry pair. |
| **Skew & IV** | ATM IV, 25Δ vertical skew, 10Δ−25Δ slope and risk reversal per maturity, with z-scores once 20 sessions are recorded; IBKR IV30 and CBOE SKEW/RVX give long history today. |
| **Risk grid** | Capital use: margin, days held and return per day by DTE at entry against your closed A14s, and the trades tying up the most margin for the least return. Every open ONE trade as a risk graph (today, a chosen date, first expiry) with date and IV-shift sliders, grouped by account, plus the whole book against a % market move (RUT beta adjustable). Greeks per trade and for the book, worst case in range, and a check that ONE's open legs match IBKR positions per account. Click a card for the large graph and leg table. |
| **Expected moves** | Every underlying you hold (open ONE trades + IBKR stocks): ATM IV, straddle, 1σ/2σ move and range per expiry (next expiry, next two Fridays, monthlies, and every expiry you hold), a cone chart with your strikes plotted, and each strike's distance from spot in σ. |
| **A14 scanner** | Put broken-wing butterflies on SPX and RUT across expiries, upper-long placements and wing widths, priced from a live TWS chain. Ranks by expected P&L at your planned exit / risk, theta / risk, P(profit), or max profit / risk; heatmap of where the edge sits (expiry × short-strike distance); SPX and RUT trend now (vs 20-day average) against how your A14s did when entered above or below it; expected return per day held; risk graph per setup; and your own A14 history from ONE grouped by DTE. |
| **P&L & Recon** | Folded in from TWS Matcher. Change in NAV today per account (with IBKR's own figure for reference), a weekly P&L grid per account (change in NAV, $ or %) with a monthly view and NAV chart, today's P&L by ticker (marked to market), ONE-vs-IBKR reconciliation (quantities; fill prices for positions opened today; FIFO vs moving-average cost-basis differences shown as information, as in TWS Matcher), stock holdings, a 7-day fill journal matched to ONE trades, and ONE import CSVs per account built from real IBKR fills. |
| **Evidence** | Every closed TimeEdge / TimeZone / Flyagonal trade from OptionStrat (before June) and ONE (from June) against market conditions on its entry day. |
| **Guide** | Step-by-step cheat sheet: getting started, a 10-minute daily routine, how to use each tab, how to read an A14 scanner row, glossary, and what to do when something looks wrong. |
| **Recorder** | Daily SPX/RUT surface snapshot (scheduled 15:40 ET weekdays while the app and TWS run), manual record, history refresh, data inventory. |

## Launch

* `Options Desk (recorder)` in the Startup folder starts the app at login (records SPX/RUT daily).
* `Desk launcher` in the Startup folder opens http://127.0.0.1:8810 whenever TradingView or TWS
  starts (once per 15 minutes). Remove it with `launcher/uninstall-launcher.ps1`.

## Data

* **IBKR first** (your subscriptions, when TWS is running): VIX, VIX9D, VIX3M, VIX6M, VIX1Y, VVIX,
  SKEW, RVX, VXN, SPX, RUT and NDX daily bars including today's live bar (every 10 min in US hours,
  hourly otherwise; client id 45), option chains for the recorder, risk grid, expected moves and
  A14 scanner, positions, NAV, fills. CBOE CSVs and yfinance are the fallback and the long history.
* **Market tab** — yfinance daily bars for ETFs, SPY and ES futures (consolidated volume, which is what
  TradingView and the Pine scripts use; IBKR's SMART volume runs ~35% lower and would skew OBV and
  Force Index); breadth computed from the
  S&P 500 and Nasdaq-100 member lists (Wikipedia) — % above 20/50/200-day SMA, overall and per
  GICS sector, standing in for TradingView's S5FI / NDFI / SKFI…; Forex Factory weekly calendar
  (US, high/medium impact); TWS account summary and fills.

* **Your own surface history** — the recorder stores ~300 option quotes per symbol per day
  (`data/desk.db`). IV is solved from mids against each expiry's put-call-parity forward,
  out-of-the-money quotes only.
* **CBOE daily index history** — VIX9D, VIX, VIX3M, VIX6M, VIX1Y, SKEW, VVIX, RVX, VXN.
  The SPX curve (9/30/93/183/365 days) is interpolated in total variance to any maturity,
  which is how SPX contango z-scores work before your own history accumulates.
* **IBKR** — 5 years of SPX/RUT daily closes and 30-day implied vol.
* **Trade journal** — newest `*-ONESummaryReport.csv` (Documents/Downloads) and newest
  OptionStrat `all-expired-by-symbol-*.xlsx` (Downloads).

## Risk grid data

Trades and legs: newest ONE Summary Report (ONE's symbols are dated one day after expiry,
so IBKR symbols are rebuilt from ONE's Expiry column). Marks: TWS snapshot (client id 42)
via "Refresh marks from TWS", and automatically after the daily recording. P&L now = ONE's
P&L (realised legs and commissions) + open legs at TWS mid. In-the-money legs use the
recorded surface IV at that strike instead of TWS's model IV.

## P&L history

P&L = change in net liquidation value (account base currency, AUD) between recorded sessions,
less deposits/withdrawals listed under `risk.cash_flows` in config.json (the TWS API doesn't report
them). IBKR's own daily P&L (`reqPnL`) is stored for reference only: summed over a week it overstated
this book's growth about threefold, because it values each day against the previous official option
closes, which are often stale for far-OTM index puts.

`account_daily` holds one row per US session and account. It was seeded from TWS Matcher's
`nav_history.json` (from 27 Aug 2026; a weekend capture is the settled Friday close and replaces
Friday's), and is written by every TWS refresh during a US session, with a final capture at
16:15 ET; overnight and weekend refreshes update that session's NAV as IBKR settles its marks.
`contract_values` keeps each position's value at every capture, so P&L by ticker is
value now − value at the last close + cash from today's fills. Fills go into `executions`.

## Expected moves and A14 scanner data

Both pull a focused chain from TWS (client id 43; live in market hours, frozen closing quotes
otherwise) on demand and automatically after the 15:40 ET recording. AM-settled monthlies (SPX, RUT)
are listed by IBKR under the Thursday last-trading day; the desk keys them by the Friday you see in
ONE. A14 legs are priced from one smile per expiry (own IV from mids, OTM puts below the forward,
OTM calls above); the exit scenario is sticky-strike Black-76, odds from a lognormal at 20-day
realised vol (or implied, or a custom vol).

## Settings

`config.json`: port, TWS host/port/client ids (41 recorder, 42 risk/accounts, 43 chains,
45 index bars), symbols, record time, expiry selection, trade files, account labels and cash flows.
Only one copy of the app runs at a time (a named mutex; a second start just opens the page). Put overrides in `config.local.json`.

## Folded in from existing projects

* TimeEdge / TimeZone / Triple Calendar rule checks: `Calendar-Scanner/docs/STRATEGIES.md`.
* Pair enumeration idea (every short × long DTE): Calendar-Scanner `buddy_atm`.
* Forward vol / contango concepts: Forward-Vol-Scanner.
