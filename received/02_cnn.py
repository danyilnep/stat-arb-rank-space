# %% [markdown]
# # Statistical arbitrage in rank space, notebook 2: CNN training and evaluation
#
# Provenance: written by a member of the 2024 team for the Mercury Capital Management quant
# team, sent to Danyil Nepyivoda on WhatsApp on 28 Nov 2024 as the cells of a QuantConnect
# research notebook. Line breaks were lost in the export and reconstructed on 2026-09-22.
# The code is otherwise as received, bugs included. It has not been run here.
# Reads the pickle written by notebook 1. Each `# %%` marker is one notebook cell.

# %%
adjusted_returns = pd.read_pickle('adjusted_returns.pkl')
phi_t = np.load('phi_t.npy')

# %%
import numpy as np
import tensorflow as tf
import pandas as pd
from sklearn.model_selection import train_test_split

X = adjusted_returns.values
r_t = adjusted_returns.shift(-1).values

X = X[:-1]
r_t = r_t[:-1]

X_train, X_test, r_t_train, r_t_test = train_test_split(X, r_t, test_size=0.3, random_state=42)

X_train = X_train[:, :, np.newaxis]
X_test = X_test[:, :, np.newaxis]

model = tf.keras.Sequential([
    tf.keras.layers.InputLayer(input_shape=(X_train.shape[1], 1)),  # Input: (n_assets, 1)
    tf.keras.layers.Conv1D(filters=8, kernel_size=3, activation='relu'),
    tf.keras.layers.MaxPooling1D(pool_size=2),
    tf.keras.layers.Conv1D(filters=16, kernel_size=3, activation='relu'),
    tf.keras.layers.GlobalAveragePooling1D(),
    tf.keras.layers.Dense(X_train.shape[1], activation='softmax')
])

@tf.keras.utils.register_keras_serializable()
def maximise_residual_return_loss(y_true, y_pred):
    """
    Custom loss function to maximise residual returns.
    """
    portfolio_returns = tf.reduce_sum(y_pred * y_true, axis=1)

    batch_size = tf.shape(y_true)[0]
    asset_count = tf.shape(y_true)[1]

    mean_returns = tf.reduce_mean(y_true, axis=1, keepdims=True)
    demeaned_returns = y_true - mean_returns

    covariance_matrix = tf.matmul(
        demeaned_returns[:, :, tf.newaxis], demeaned_returns[:, tf.newaxis, :]
    ) / tf.cast(asset_count, tf.float32)

    # Portfolio variance: w'Σw
    portfolio_variance = tf.reduce_sum(
        y_pred[:, :, tf.newaxis] * tf.matmul(covariance_matrix, y_pred[:, :, tf.newaxis]), axis=(1, 2)
    )

    loss = tf.reduce_mean(portfolio_variance - portfolio_returns)
    return loss

model.compile(optimizer='adam', loss=maximise_residual_return_loss, metrics=['mae'])
model.fit(X_train, r_t_train, epochs=50, batch_size=64, validation_data=(X_test, r_t_test))

predicted_weights = model.predict(X_test)

predicted_weights /= np.sum(predicted_weights, axis=1, keepdims=True)

predicted_weights_df = pd.DataFrame(predicted_weights, columns=adjusted_returns.columns)

# %%
import matplotlib.pyplot as plt

portfolio_returns = np.sum(predicted_weights * r_t_test, axis=1)

cumulative_returns = np.cumprod(1 + portfolio_returns) - 1

equal_weights = np.ones(r_t_test.shape[1]) / r_t_test.shape[1]
benchmark_returns = np.sum(equal_weights * r_t_test, axis=1)
benchmark_cumulative_returns = np.cumprod(1 + benchmark_returns) - 1

plt.figure(figsize=(10, 6))
plt.plot(cumulative_returns, label='Predicted Weights Portfolio', color='blue')
plt.plot(benchmark_cumulative_returns, label='Equal-Weight Benchmark', color='orange', linestyle='--')
plt.title('Cumulative Returns: Predicted vs. Benchmark')
plt.xlabel('Time Step')
plt.ylabel('Cumulative Return')
plt.legend()
plt.grid()
plt.show()

total_return = cumulative_returns[-1]
benchmark_total_return = benchmark_cumulative_returns[-1]
sharpe_ratio = np.mean(portfolio_returns) / np.std(portfolio_returns)  # Assuming no risk-free rate

print(f"Total Return (Predicted Weights Portfolio): {total_return:.2%}")
print(f"Total Return (Equal-Weight Benchmark): {benchmark_total_return:.2%}")
print(f"Sharpe Ratio (Predicted Weights Portfolio): {sharpe_ratio:.2f}")

# %%
from tensorflow.keras.utils import serialize_keras_object
from tensorflow.keras import utils
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Flatten
import json
qb = QuantBook()
model_str = json.dumps(serialize_keras_object(model))
model_key = "model"
qb.ObjectStore.Save(model_key, model_str)
