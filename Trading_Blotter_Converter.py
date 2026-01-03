#!/usr/bin/env python3
"""
Standalone converter: read the Binance CSV/XLSX and write Trading_Daily_Blotter.md
Heuristics-based: looks for common column names. Adjust mappings if needed.
"""
import pandas as pd
from pathlib import Path
import json
import os
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Use repository/script-relative paths so other users can run this from their clones.
script_dir = Path(__file__).resolve().parent
cwd = Path.cwd()

# Find CSV/XLSX candidates by common Binance export filename pattern in script dir then cwd.
def newest(files):
    return max(files, key=lambda p: p.stat().st_mtime) if files else None

csv_candidates = list(script_dir.glob('order history files/Binance-Cross Margin Order History*.csv')) + list(cwd.glob('order history files/Binance-Cross Margin Order History*.csv'))
xlsx_candidates = list(script_dir.glob('order history files/Binance-Cross Margin Order History*.xlsx')) + list(cwd.glob('order history files/Binance-Cross Margin Order History*.xlsx'))

csv_file = newest(csv_candidates)
xlsx_file = newest(xlsx_candidates)

src = None
# Prefer existing CSV; if only XLSX exists, convert it to CSV first (saved next to the XLSX)
if csv_file:
    src = csv_file
elif xlsx_file:
    # convert to CSV with same stem if not already present
    src = xlsx_file.with_suffix('.csv')
    if not src.exists():
        print(f'Converting {xlsx_file} -> {src}')
        df_temp = pd.read_excel(xlsx_file, engine='openpyxl')
        df_temp.to_csv(src, index=False, encoding='utf-8-sig')
else:
    # fallback: any csv/xlsx in script dir or cwd
    any_csv = list(script_dir.glob('*.csv')) + list(cwd.glob('*.csv'))
    any_xlsx = list(script_dir.glob('*.xlsx')) + list(cwd.glob('*.xlsx'))
    if any_csv:
        src = newest(any_csv)
    elif any_xlsx:
        picked = newest(any_xlsx)
        src = picked.with_suffix('.csv')
        if not src.exists():
            print(f'Converting {picked} -> {src}')
            df_temp = pd.read_excel(picked, engine='openpyxl')
            df_temp.to_csv(src, index=False, encoding='utf-8-sig')
    else:
        raise RuntimeError('No CSV or XLSX files found in the repository/script directory.')

# write outputs next to the script (relative paths)
dst = script_dir / 'Trading_Daily_Blotter.md'
state_path = script_dir / 'blotter_state.json'
charts_dir = script_dir / 'charts'
os.makedirs(charts_dir, exist_ok=True)

# read csv first, fallback to excel
try:
    df = pd.read_csv(src, encoding='utf-8-sig')
except Exception:
    try:
        df = pd.read_excel(src.with_suffix('.xlsx'), engine='openpyxl')
    except Exception:
        raise

# identify datetime column (we expect "Date(UTC)" or similar) and convert to Asia/Taipei (UTC+8)
date_col = None
for c in df.columns:
    if 'date' in c.lower() or 'utc' in c.lower() or 'time' in c.lower():
        date_col = c
        break

if date_col is None:
    raise RuntimeError('No date/time column found in CSV')

# parse as UTC then convert to Taipei timezone
df['_ts_utc'] = pd.to_datetime(df[date_col], errors='coerce')
if df['_ts_utc'].dt.tz is None:
    # treat as UTC-naive timestamps that are actually UTC
    df['_ts_utc'] = pd.to_datetime(df[date_col], errors='coerce', utc=True)
else:
    df['_ts_utc'] = pd.to_datetime(df[date_col], errors='coerce').dt.tz_convert('UTC')

df['_ts_taipei'] = df['_ts_utc'].dt.tz_convert('Asia/Taipei')
df['__date'] = df['_ts_taipei'].dt.date

dates = sorted(df['__date'].dropna().unique())
if len(dates) == 0:
    dates = [None]

md = []
md.append('# Trading Daily Blotter')

# persistent buy/sell queues across days (leftovers carry over)
from collections import deque
# load persistent state if exists
if state_path.exists():
    try:
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        processed_orders = set(state.get('processed_orders', []))
        buy_q = deque(state.get('buy_q', []))
        sell_q = deque(state.get('sell_q', []))
        history = state.get('history', {})  # { 'YYYY-MM-DD': {'profit': x, 'fee': y} }
    except Exception:
        processed_orders = set()
        buy_q = deque()
        sell_q = deque()
        history = {}
else:
    processed_orders = set()
    buy_q = deque()
    sell_q = deque()
    history = {}

new_processed = set()

def to_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0

# helper to format currency values
def fmt(x):
    try:
        return f'{x:,.2f}'
    except Exception:
        return str(x)

for d in dates:
    if d is None:
        day_df = df
        day_str = ''
    else:
        day_df = df[df['__date'] == d].copy()
        day_str = d.strftime('%Y-%m-%d')

    md.append('\n')
    md.append(f'## {day_str}')
    # Table columns: index, B/S(Type), Amount(Total), Currency Pair(Base/Quote), Rate(AvgTrading Price), Order Amount, status, note, Order No.
    md.append('| # | B/S | Amount (Total) | Currency Pair | Rate (Avg) | Order Amount | Status | Note | Order No. |')
    md.append('|---:|:---:|---:|---:|---:|---:|---:|---:|---:|')


    # per-day accumulators
    total_fee_quote = 0.0
    profit = 0.0


    # We'll iterate in chronological order (use _ts_utc)
    day_df = day_df.sort_values(by='_ts_utc')

    # Iterate rows as Series to reliably access columns with spaces or punctuation
    def getcol(row, options):
        for c in options:
            if c in day_df.columns:
                return row.get(c)
        return None

    for i, (_, row) in enumerate(day_df.iterrows(), start=1):
        side = getcol(row, ['Type', 'type', 'Side', 'side']) or ''
        total_val = getcol(row, ['Total', 'total'])

        base = getcol(row, ['Base Asset'])
        quote = getcol(row, ['Quote Asset'])
        if base and quote:
            pair = f"{base}/{quote}"
        else:
            pair = getcol(row, ['Pair']) or ''

        rate = getcol(row, ['AvgTrading Price', 'AvgTradingPrice', 'AvgTrading_Price', 'Avg Trading Price'])
        if rate is None:
            rate = getcol(row, ['AvgTrading Price', 'Order Price', 'Order Price'])

        order_amount = getcol(row, ['Order Amount', 'Filled'])

        order_no = getcol(row, ['Order No.'])
        order_no_key = None if order_no is None else str(order_no)
        st = getcol(row, ['Status']) or ''

        # timestamp hh:mm in Taipei
        hhmm = ''
        try:
            if '_ts_taipei' in day_df.columns:
                hhmm = pd.to_datetime(row['_ts_taipei']).strftime('%H:%M')
        except Exception:
            hhmm = ''

        status_label = f"{hhmm} {str(st)}".strip()
        note_field = ''

        # If this order was already processed in a previous run, skip computations but list it
        # Keep the Note column empty so users can add their own comments/review later.
        if order_no_key is not None and order_no_key in processed_orders:
            md.append(f"| {i} | {side} | {fmt(to_float(total_val)) if total_val not in (None, '') else ''} | {pair} | {fmt(to_float(rate)) if rate not in (None, '') else ''} | {order_amount if order_amount not in (None, '') else ''} | {status_label} |  | {order_no if order_no not in (None, '') else ''} |")
            continue

        md.append(f"| {i} | {side} | {fmt(to_float(total_val)) if total_val not in (None, '') else ''} | {pair} | {fmt(to_float(rate)) if rate not in (None, '') else ''} | {order_amount if order_amount not in (None, '') else ''} | {status_label} | {note_field} | {order_no if order_no not in (None, '') else ''} |")

        is_filled = str(st).lower() == 'filled'
        if is_filled:
            qty = to_float(order_amount)
            price = to_float(rate)
            total_quote = to_float(total_val)
            total_fee_quote += total_quote

            # Realize P/L by matching against prior opposite-side leftovers first
            if str(side).upper() == 'BUY':
                # match against existing sells (closing shorts)
                remaining = qty
                while remaining > 1e-12 and sell_q:
                    s = sell_q[0]
                    m = min(remaining, s['qty'])
                    # earlier we sold at s['price'], now we buy at price -> profit = (sell_price - buy_price)
                    profit += m * (s['price'] - price)
                    s['qty'] -= m
                    remaining -= m
                    if abs(s['qty']) < 1e-12:
                        sell_q.popleft()
                # leftover becomes a long position
                if remaining > 1e-12:
                    buy_q.append({'qty': remaining, 'price': price})
            else:
                # SELL: match against existing buys (closing longs)
                remaining = qty
                while remaining > 1e-12 and buy_q:
                    b = buy_q[0]
                    m = min(remaining, b['qty'])
                    # we sell now at price, earlier bought at b['price'] -> profit = (sell_price - buy_price)
                    profit += m * (price - b['price'])
                    b['qty'] -= m
                    remaining -= m
                    if abs(b['qty']) < 1e-12:
                        buy_q.popleft()
                # leftover becomes a short position
                if remaining > 1e-12:
                    sell_q.append({'qty': remaining, 'price': price})

        # mark as processed so next runs skip it
        if order_no_key is not None:
            new_processed.add(order_no_key)

    # leftover positions: compute USD value using leftover qty * price (queues persist across days)
    long_usd = sum(b['qty'] * b['price'] for b in buy_q)
    short_usd = sum(s['qty'] * s['price'] for s in sell_q)

    fee_val = total_fee_quote * 0.001

    md.append('\n')
    # Position line: choose LONG USD / SHORT USD based on net leftover
    md.append(f'Position: LONG USD: {fmt(long_usd)}; SHORT USD: {fmt(short_usd)}  ')
    md.append(f'PL: {fmt(profit)}')
    md.append(f'Fee: {fmt(fee_val)}')
    md.append('')
    md.append('**Review:** ')
    # record today's profit/fee into history (only for days with a date string)
    if day_str:
        h = history.get(day_str, {'profit': 0.0, 'fee': 0.0})
        h['profit'] = h.get('profit', 0.0) + profit
        h['fee'] = h.get('fee', 0.0) + fee_val
        history[day_str] = h

# After processing all days: persist state and generate charts for last 30 days
# update processed_orders
processed_orders.update(new_processed)

# save state
state = {
    'processed_orders': list(processed_orders),
    'buy_q': list(buy_q),
    'sell_q': list(sell_q),
    'history': history,
}
with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

# prepare last-30-days chart data
if history:
    hist_dates = sorted(history.keys())
    # determine last date (use last key)
    last_date = datetime.strptime(hist_dates[-1], '%Y-%m-%d').date()
else:
    last_date = datetime.utcnow().date()

start_date = last_date - timedelta(days=29)
days = [start_date + timedelta(days=i) for i in range(30)]
profits = [history.get(d.strftime('%Y-%m-%d'), {}).get('profit', 0.0) for d in days]
fees = [history.get(d.strftime('%Y-%m-%d'), {}).get('fee', 0.0) for d in days]

# daily profit bar chart
fig, ax = plt.subplots(figsize=(12, 4))
xs = [d.strftime('%m-%d') for d in days]
colors = ['green' if v > 0 else 'red' if v < 0 else 'gray' for v in profits]
ax.bar(xs, profits, color=colors)
ax.set_title('Daily P/L (last 30 days)')
ax.set_ylabel('P/L (quote currency)')
ax.tick_params(axis='x', rotation=45)
plt.tight_layout()
daily_chart = charts_dir / 'daily_profit_last30.png'
fig.savefig(daily_chart)
plt.close(fig)

# pie chart of PL vs Fee for last 30 days (use absolute net PL to avoid negatives in pie)
net_pl = sum(profits)
net_fee = sum(fees)
pie_chart = charts_dir / 'pl_fee_pie_last30.png'
if abs(net_pl) > 1e-9 or net_fee > 1e-9:
    labels = ['Net P/L', 'Fee']
    sizes = [abs(net_pl), net_fee]
    fig2, ax2 = plt.subplots(figsize=(6, 6))
    # autopct function that shows both percentage and absolute value
    def make_autopct(values):
        def my_autopct(pct):
            total = sum(values)
            val = pct * total / 100.0
            return f"{pct:.1f}%\n({val:,.2f})"
        return my_autopct

    ax2.pie(sizes, labels=labels, autopct=make_autopct(sizes), colors=['#2ca02c', '#ff7f0e'])
    ax2.set_title('Net P/L vs Fee (last 30 days)')
    ax2.axis('equal')
    fig2.savefig(pie_chart)
    plt.close(fig2)

# append chart images to markdown
md.append('\n')
md.append('### Charts (last 30 days)')
md.append(f'![Daily P/L]({os.path.relpath(daily_chart, dst.parent)})')
if pie_chart.exists():
    md.append(f'![P/L vs Fee]({os.path.relpath(pie_chart, dst.parent)})')

# write output
dst.write_text('\n'.join(md), encoding='utf-8')
print(f'Wrote markdown to: {dst}\nState saved to: {state_path}\nCharts saved to: {charts_dir}')
