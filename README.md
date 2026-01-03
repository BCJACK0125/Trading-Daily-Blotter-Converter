# Trading Daily Blotter Converter (v1.0.0)

A small Python utility that converts a Binance Cross Margin Order History CSV/XLSX export into a human-friendly daily blotter in Markdown. It computes realized P/L using FIFO matching across days, estimates fees, keeps persistent state so runs are idempotent, and generates simple charts for the most recent 30 days.

## Features

- Convert Binance CSV/XLSX order history to `Trading_Daily_Blotter.md` with one daily section and a table of orders.
- Timezone aware: converts recorded UTC timestamps to Asia/Taipei (UTC+8) for display.
- Mapping of key columns: B/S, Amount (Total), Currency Pair, Rate (AvgTrading Price), Order Amount (Filled), Status, Note (left empty for user review), Order No.
- FIFO matching for realized P/L including matches with leftover positions carried from previous days.
- Fee estimation: Fee = sum(Total of filled orders) * 0.001 (quote currency).
- Persistent state: `blotter_state.json` stores processed Order No.s, leftover buy/sell queues and per-day history so you can re-run the converter without double-counting.
- Charts: generates `charts/daily_profit_last30.png` (daily P/L bar chart) and `charts/pl_fee_pie_last30.png` (Net P/L vs Fee pie chart that shows percentage and absolute values).

## Quick start

1. Put your Binance Cross Margin Order History CSV or XLSX in the repository root. By default the script expects the file named like:

   `Binance-Cross Margin Order History-YYYYMMDDHHMM.csv`

   or the `.xlsx` counterpart.

2. Install dependencies (use the Python environment you prefer):

```ps1
python -m pip install -r requirements.txt
```

3. Run the converter (Windows `cmd` or PowerShell):

```ps1
python "convert_to_md.py"
```

4. Output files created/updated:

- `Trading_Daily_Blotter.md` — the generated Markdown blotter.
- `blotter_state.json` — persistent state used for idempotency and carry-over positions.
- `charts/` — contains `daily_profit_last30.png` and `pl_fee_pie_last30.png`.

## Calculation rules (how numbers are derived)

These are the exact calculation rules used by v1.0.0:

- Timestamp conversion: the script finds the first column whose name contains `date`, `utc` or `time` and parses it as UTC. It then converts timestamps to `Asia/Taipei` timezone for display and grouping by date.
- Side / Type: maps common column names like `Type`, `Side`, `type` to the B/S column in the MD.
- Amount: the `Total` column (quote-currency amount) is used for the Amount column in the blotter and for fee estimation.
- Order Amount: uses `Order Amount` or falls back to `Filled` when available; this quantity is used for matching and P/L.
- Rate: uses `AvgTrading Price` (or common variants) as execution price for P/L calculation. If absent, a price may be missing and calculations could be approximate.
- FIFO realized P/L: when a filled order appears, it attempts to match its quantity against the opposite-side leftover queue (persisted across days) using FIFO. For example, a BUY will first match against earlier sells (closing existing shorts); a SELL matches earlier buys (closing longs). Realized profit for a matched quantity m is:

  - For closing a short (we sold earlier at S_price, now buy at B_price): profit = m * (S_price - B_price)
  - For closing a long (we bought earlier at B_price, now sell at S_price): profit = m * (S_price - B_price)

  Unmatched remainder becomes a carried-over position in the buy or sell queue.
- Fee: computed as Fee = sum(Total of filled rows for the day) * 0.001 (i.e., 0.1% of trade value in quote currency).

## Idempotency and state

- The converter uses `Order No.` as the idempotency key to avoid double-processing rows between runs. Processed order numbers are stored in `blotter_state.json` and skipped on subsequent runs.
- Leftover positions (buy and sell queues) are stored in the same state file so carry-over positions are preserved across runs.

Notes:
- If you prefer to only mark orders as processed when `Status == Filled`, you can adjust the script to add `Order No.` to the processed list only for filled rows.

## Files in this repository

- `convert_to_md.py` — main script that does the conversion and chart generation.
- `Trading_Daily_Blotter.md` — generated output (not committed by default unless desired).
- `blotter_state.json` — persistent state file created on first run.
- `charts/` — generated images.
- `requirements.txt` — Python dependencies (see below).

## Assumptions & limitations

- Column header heuristics: the script tries common header names. If your CSV/XLSX uses different column names, you may need to adjust the `getcol()` options inside `convert_to_md.py`.
- Price availability: accurate P/L depends on a valid execution price (`AvgTrading Price`). Missing prices will lead to 0 or inaccurate P/L entries.
- Currency handling: the script treats `Total` as quote-currency value and all P/L/fee computations are in that quote currency. There's no FX conversion between different quote currencies.
- Matching strategy: current behavior is FIFO across all executed quantities. If you require matching by order id or by other batching rules, the logic will need to be adapted.

## Future improvements (ideas)

- Add CLI flags to specify input file, output path, timezone, and fee rate.
- Add unit tests for the FIFO matching logic and edge cases (partial fills, cancellations).
- Add multi-currency support and currency-normalized reports.
- Improve charts and add CSV export for accounting systems.

## License

This project is released under the MIT License.

---

If you'd like, I can also create a short `requirements.txt` and a minimal `README` badge or a GitHub Actions workflow to generate the blotter automatically on push — tell me which you'd prefer next.
