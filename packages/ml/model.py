"""A small, dependency-free model of *which signals predict profitable trades*.

Fits an L2-regularized logistic regression (full-batch gradient descent, numpy
only) on the feature/label store from ``dataset.py``. The point is not a
deployable predictor trained on a handful of trips — it is an **interpretive,
in-sample** read on the strategy: which signals/readings associate with winning
trades, and by how much above the base rate.

Everything is deterministic (zero init, fixed iteration count) so the output is
reproducible and unit-testable. Training is O(iterations · n · d) on tiny
matrices — microseconds to milliseconds — so the backtest worker can fit it
inline on every run, exactly like attribution.

Degenerate inputs are handled rather than raised: too few samples or a single
outcome class yields ``fitted=False`` with a ``reason``; the empirical
per-signal edges are still reported (they need no model).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from packages.ml.dataset import COUNT_FEATURE, TrainingDataset

# Below this many trips, an in-sample fit is pure noise — report empirically
# but don't pretend to have learned weights.
MIN_SAMPLES_TO_FIT = 8


@dataclass(frozen=True)
class SignalFeatureWeight:
    """One feature's learned weight, in standardized space (so magnitudes are
    comparable across features). Positive ⇒ pushes toward 'profitable'."""

    feature: str
    weight: float


@dataclass(frozen=True)
class SignalEdge:
    """Per-signal summary: how trades tagged with this signal actually did
    (empirical) and how the model rates them (predicted), versus the base rate.
    """

    name: str
    num_trades: int
    empirical_profit_rate: float
    mean_predicted_prob: float
    # (mean predicted prob − base rate), in percentage points. The model's view
    # of this signal's edge; positive = better-than-average.
    lift_vs_base_pp: float


@dataclass(frozen=True)
class SignalEdgeModel:
    """Fitted (or gracefully unfitted) signal-edge model + its report."""

    n_samples: int
    n_features: int
    base_profit_rate: float
    fitted: bool
    reason: str | None  # why not fitted (None when fitted)
    train_accuracy: float | None
    train_log_loss: float | None
    feature_weights: list[SignalFeatureWeight]
    signal_edges: list[SignalEdge]
    # Hyperparameters, recorded for reproducibility.
    iterations: int
    learning_rate: float
    l2: float


def _sigmoid(z: np.ndarray) -> np.ndarray:
    # Stable: clip the linear term so exp can't overflow on extreme logits.
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def _standardize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Zero-mean / unit-std columns; constant columns (std 0) pass through."""
    mu = X.mean(axis=0)
    sigma = X.std(axis=0)
    safe_sigma = np.where(sigma == 0.0, 1.0, sigma)
    return (X - mu) / safe_sigma, mu, safe_sigma


def _empirical_edges(
    dataset: TrainingDataset, probs: np.ndarray, base: float
) -> list[SignalEdge]:
    """Per-signal empirical + predicted edge, sorted by predicted lift desc."""
    edges: list[SignalEdge] = []
    for name in dataset.signal_names:
        col = dataset.active_column_for(name)
        if col is None:
            continue
        mask = dataset.X[:, col] > 0.5
        n = int(mask.sum())
        if n == 0:
            continue
        emp = float(dataset.y_class[mask].mean())
        pred = float(probs[mask].mean())
        edges.append(
            SignalEdge(
                name=name,
                num_trades=n,
                empirical_profit_rate=emp,
                mean_predicted_prob=pred,
                lift_vs_base_pp=(pred - base) * 100.0,
            )
        )
    edges.sort(key=lambda e: e.lift_vs_base_pp, reverse=True)
    return edges


def train_signal_edge_model(
    dataset: TrainingDataset,
    *,
    iterations: int = 500,
    learning_rate: float = 0.1,
    l2: float = 1e-2,
) -> SignalEdgeModel:
    """Fit the logistic model and assemble the report.

    Always returns a ``SignalEdgeModel``; ``fitted`` is False (with a reason)
    when the data can't support a fit, in which case predicted probabilities
    fall back to the base rate and only empirical edges are meaningful.
    """
    n, d = dataset.n_samples, dataset.n_features
    base = dataset.base_profit_rate
    y = dataset.y_class.astype(float)

    def _unfitted(reason: str) -> SignalEdgeModel:
        probs = np.full(n, base, dtype=float)
        return SignalEdgeModel(
            n_samples=n,
            n_features=d,
            base_profit_rate=base,
            fitted=False,
            reason=reason,
            train_accuracy=None,
            train_log_loss=None,
            feature_weights=[],
            signal_edges=_empirical_edges(dataset, probs, base) if n else [],
            iterations=iterations,
            learning_rate=learning_rate,
            l2=l2,
        )

    if n < MIN_SAMPLES_TO_FIT:
        return _unfitted(
            f"Only {n} closed trade(s); need ≥{MIN_SAMPLES_TO_FIT} to fit a model."
        )
    if len(np.unique(y)) < 2:
        only = "all profitable" if y[0] > 0.5 else "all losing"
        return _unfitted(f"Trades are single-class ({only}); nothing to separate.")

    # --- Fit: full-batch gradient descent on standardized features ---
    Xs, _mu, _sigma = _standardize(dataset.X)
    w = np.zeros(d, dtype=float)
    b = 0.0
    for _ in range(iterations):
        p = _sigmoid(Xs @ w + b)
        err = p - y
        grad_w = Xs.T @ err / n + l2 * w
        grad_b = float(err.mean())
        w -= learning_rate * grad_w
        b -= learning_rate * grad_b

    probs = _sigmoid(Xs @ w + b)
    preds = (probs >= 0.5).astype(float)
    accuracy = float((preds == y).mean())
    eps = 1e-12
    log_loss = float(
        -np.mean(y * np.log(probs + eps) + (1 - y) * np.log(1 - probs + eps))
    )

    # Standardized-space weights, most influential first; the count feature is
    # kept but labeled by its own name.
    weights = [
        SignalFeatureWeight(feature=name, weight=float(wi))
        for name, wi in zip(dataset.feature_names, w, strict=True)
    ]
    weights.sort(key=lambda fw: abs(fw.weight), reverse=True)

    return SignalEdgeModel(
        n_samples=n,
        n_features=d,
        base_profit_rate=base,
        fitted=True,
        reason=None,
        train_accuracy=accuracy,
        train_log_loss=log_loss,
        feature_weights=weights,
        signal_edges=_empirical_edges(dataset, probs, base),
        iterations=iterations,
        learning_rate=learning_rate,
        l2=l2,
    )


# ============================================================
# Serialization (JSONB persistence / API response)
# ============================================================
def model_to_dict(model: SignalEdgeModel) -> dict:
    """JSON-serializable view of a SignalEdgeModel (all plain floats/ints)."""
    return {
        "n_samples": model.n_samples,
        "n_features": model.n_features,
        "base_profit_rate": model.base_profit_rate,
        "fitted": model.fitted,
        "reason": model.reason,
        "train_accuracy": model.train_accuracy,
        "train_log_loss": model.train_log_loss,
        "feature_weights": [
            {"feature": fw.feature, "weight": fw.weight}
            for fw in model.feature_weights
        ],
        "signal_edges": [
            {
                "name": e.name,
                "num_trades": e.num_trades,
                "empirical_profit_rate": e.empirical_profit_rate,
                "mean_predicted_prob": e.mean_predicted_prob,
                "lift_vs_base_pp": e.lift_vs_base_pp,
            }
            for e in model.signal_edges
        ],
        "hyperparams": {
            "iterations": model.iterations,
            "learning_rate": model.learning_rate,
            "l2": model.l2,
        },
        "count_feature": COUNT_FEATURE,
    }
