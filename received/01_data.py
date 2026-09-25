# %% [markdown]
# # Statistical arbitrage in rank space, notebook 1: data gathering and processing
#
# Provenance: written by a member of the 2024 team for the Mercury Capital Management
# quant team, led by Danyil Nepyivoda, and sent to Danyil on WhatsApp on
# 28 Nov 2024 as the cells of a QuantConnect research notebook. The WhatsApp export
# dropped every line break; indentation and cell boundaries were reconstructed on
# 2026-09-22. The code is otherwise as received, bugs included. It has not been run here.
# Each `# %%` marker is one notebook cell.

# %%
from AlgorithmImports import *
import pandas as pd
import tensorflow

market_cap = QuantBook()
start_time = pd.to_datetime('01/01/2015')
end_time = pd.to_datetime('01/01/2016')

def filter_function(fundamentals):
    sorted_by_market_cap = sorted(
        [f for f in fundamentals if not np.isnan(f.market_cap)],
        key=lambda f: f.market_cap
    )
    return [f.symbol for f in sorted_by_market_cap]

universe = market_cap.add_universe(filter_function)
market_history = market_cap.history(universe, start_time, end_time, Resolution.DAILY)

data = []
for (universe_symbol, time), fundamental in market_history.items():
    highest_market_cap = sorted(fundamental, key=lambda x: x.market_cap)[-40:]  # lower this if Kernel crashes
    data.extend(
        {"Time": time, "Symbol": f.symbol.Value, "MarketCap": f.market_cap}
        for f in highest_market_cap
    )
df = pd.DataFrame(data)
df = df.sort_values(by="MarketCap", ascending=False)
df = df.drop_duplicates(subset="Symbol", keep="first")
tickers = []
for i in df['Symbol']:
    tickers.append(i)
del data

# %%
import gc
start_time = pd.to_datetime('01/01/2015')
end_time = pd.to_datetime('01/01/2016')
qb = QuantBook()

market_cap_df = pd.DataFrame(columns=['symbol', 'time', 'marketcap'])

batch_size = 10

for i in range(0, len(tickers), batch_size):
    batch_tickers = tickers[i:i + batch_size]
    batch_data = []

    for ticker in batch_tickers:
        symbol = Symbol.create(ticker, SecurityType.EQUITY, Market.USA)
        temp_df = qb.history(Fundamental, symbol, start_time, end_time)

        if temp_df.empty:
            print(f"No data for {ticker}.")
            continue
        if 'marketcap' not in temp_df.columns:
            print(f"'marketcap' column not found for {ticker}.")
            continue

        temp_df = temp_df[['marketcap']]
        temp_df = temp_df.reset_index()
        temp_df['symbol'] = temp_df['symbol'].apply(lambda x: str(x))
        temp_df.columns = ['symbol', 'time', 'marketcap']
        batch_data.append(temp_df)

    if batch_data:
        batch_df = pd.concat(batch_data, ignore_index=True)
        market_cap_df = pd.concat([market_cap_df, batch_df], ignore_index=True)

del batch_df

market_cap_df = market_cap_df[['symbol', 'time', 'marketcap']]
market_cap_df['symbol'] = market_cap_df['symbol'].str.split(' ').str[0]

# %%
import os
import gc
import pandas as pd

output_dir = "batch_data"
os.makedirs(output_dir, exist_ok=True)

# Assume tickers, batch_size, and other necessary variables are defined
history_data = []

for i in range(0, len(tickers), batch_size):
    batch_tickers = tickers[i:i + batch_size]
    symbols = [qb.add_equity(ticker, Resolution.MINUTE).symbol for ticker in batch_tickers]

    history = qb.history(TradeBar, symbols, start_time, end_time, Resolution.MINUTE)
    if history.empty:
        print(f"No data found for batch {i}-{i+batch_size-1}.")
        continue
    history = history.reset_index()
    history['symbol'] = history['symbol'].apply(lambda x: str(x))
    history = history[['symbol', 'time', 'close']]

    history_data.append(history)
    del history
    gc.collect()

close_price_df = pd.concat(history_data, ignore_index=True)

del history_data
gc.collect()

# %%
market_cap_df['time'] = pd.to_datetime(market_cap_df['time'], errors='coerce')
close_price_df['time'] = pd.to_datetime(close_price_df['time'], errors='coerce')

market_cap_df['date'] = market_cap_df['time'].dt.date
close_price_df['date'] = close_price_df['time'].dt.date

start_of_day_prices = close_price_df[['symbol', 'date', 'close']].drop_duplicates(subset=['symbol', 'date'])

market_cap_df = pd.merge(market_cap_df, start_of_day_prices, on=['symbol', 'date'], how='left')

market_cap_df['shares_outstanding'] = market_cap_df['marketcap'] / market_cap_df['close']

minute_data = pd.merge(close_price_df[['symbol', 'time', 'date', 'close']], market_cap_df[['symbol', 'date', 'shares_outstanding']], on=['symbol', 'date'], how='left')
minute_data.fillna(method='ffill', inplace=True)
minute_data['minute_market_cap'] = minute_data['close'] * minute_data['shares_outstanding']

tickers_1 = minute_data['symbol'].unique().tolist()

# %%
minute_data = minute_data[minute_data['time'] > pd.to_datetime('02/02/2015')]
minute_data = minute_data[['symbol', 'time', 'minute_market_cap']]

# %%
import gc

del market_cap_df
del close_price_df
del start_of_day_prices

# Step 2: Run garbage collection to free up memory
gc.collect()

minute_data = minute_data.pivot(index='time', columns='symbol', values='minute_market_cap')
minute_data = minute_data.reset_index()

# %%
minute_data['time'] = pd.to_datetime(minute_data['time'])
minute_data.set_index('time', inplace=True)

# Calculate the percentage change for each symbol (axis=0 means calculating along rows)
minute_data = minute_data.pct_change()

# %%
minute_data = minute_data.drop(index=minute_data.index[0])

# %%
import gc
gc.collect()
qb = QuantBook()
qb.dataset_symbol = qb.add_data(USTreasuryYieldCurveRate, "USTYCR").symbol
history_df = qb.history(qb.dataset_symbol, start_time, end_time, Resolution.DAILY)
import pandas as pd
history_df = history_df[['tenyear']]
import pandas as pd

history_df = history_df[['tenyear']]
history_df = history_df.reset_index()

history_df['symbol'] = history_df['symbol'].apply(lambda x: str(x))
history_df.columns = ['symbol', 'time', 'tenyear']

history_df = history_df.drop('symbol', axis=1)

history_df['time'] = pd.to_datetime(history_df['time'], utc=True)

history_df['date'] = history_df['time'].dt.date

history_df.set_index('time', inplace=True)

def resample_group(group):
    group_resampled = group.resample('T').ffill()
    group_resampled['tenyear'] = group_resampled['tenyear'] / (365 * 24 * 60)
    return group_resampled

risk_free = history_df.groupby('date').apply(resample_group)
risk_free.reset_index(drop=True, inplace=True)

# %%
expanded_data = []
for _, row in risk_free.iterrows():
    date_range = pd.date_range(row['date'], periods=1440, freq='T')
    expanded_data.append(pd.DataFrame({
        'time': date_range,
        'tenyear': [row['tenyear']] * len(date_range)
    }))

expanded_df = pd.concat(expanded_data, ignore_index=True)

risk_free = expanded_df
del expanded_df
del expanded_data

# %%
gc.collect()
import pandas as pd

minute_data.index = pd.to_datetime(minute_data.index)
risk_free['time'] = pd.to_datetime(risk_free['time'])
minute_data_reset = minute_data.reset_index()

merged_df = pd.merge(minute_data_reset, risk_free, on='time', how='left')

asset_symbols = merged_df.columns.difference(['time', 'tenyear'])

for symbol in asset_symbols:
    merged_df[symbol + '_res'] = merged_df[symbol] - merged_df['tenyear']

merged_df.drop(columns=asset_symbols, inplace=True)
merged_df.drop('tenyear', axis=1, inplace=True)

merged_df.set_index('time', inplace=True)

print(merged_df.head())

merged_df
del minute_data
del minute_data_reset
del risk_free

# %%
adjusted_returns = merged_df
del merged_df
adjusted_returns

# %%
gc.collect()
import numpy as np
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer

# Replace infinity values with NaN (in-place)
adjusted_returns.replace([np.inf, -np.inf], np.nan, inplace=True)

# Step 1: Handle missing values (Impute missing values with the mean)
imputer = SimpleImputer(strategy='mean')
adjusted_returns_imputed = imputer.fit_transform(adjusted_returns)

# Step 2: Apply PCA (fit directly on imputed data to avoid holding multiple copies)
pca = PCA(n_components=1)  # 1 component for rank as per paper
pca.fit(adjusted_returns_imputed)

# Step 3: Extract β_t (the loadings from PCA)
beta_t = pca.components_[0]
omega_t = pca.explained_variance_ratio_

# Step 4: Compute Φ_t = (I - β_t ω_t)
I = np.eye(len(adjusted_returns.columns))
beta_omega = np.outer(beta_t, omega_t)  # Outer product of β_t and ω_t
phi_t = I - beta_omega  # This is the transformation matrix Φ_t

# Step 5: Compute the residuals (ϵ_t) and assign them to the DataFrame
residual_returns = np.dot(phi_t, adjusted_returns_imputed.T).T
for i, symbol in enumerate(adjusted_returns.columns):
    adjusted_returns[symbol + '_residual'] = residual_returns[:, i]

# Step 6: Drop the original columns (half of them)
adjusted_returns.drop(columns=adjusted_returns.columns[:len(adjusted_returns.columns)//2], inplace=True)

# Clean up: Remove imputed data and transformation matrices to save memory
del adjusted_returns_imputed, beta_omega

# %%
adjusted_returns.to_pickle('adjusted_returns.pkl')
np.save('phi_t.npy', phi_t)
