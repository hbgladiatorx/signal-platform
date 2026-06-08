"""Machine-learning layer over backtest results (Phase 3).

The substrate is the per-bar ``SignalEvent`` log every strategy emits via
``ctx.signal(...)`` plus the closed round trips analytics pairs out of the
fills. ``dataset.py`` turns those into a labeled feature matrix (the
feature/label store); ``model.py`` fits a small, dependency-free model that
learns *which signals predict profitable trades*.

Public API::

    from packages.ml import (
        build_dataset,
        TrainingDataset,
        train_signal_edge_model,
        SignalEdgeModel,
        model_to_dict,
    )

Deliberately numpy-only: no scikit-learn / torch, so it trains in milliseconds
on the existing box and stays fully deterministic (and therefore testable).
The feature store is the plug-in point for heavier models (GBM, RL) later.
"""
from packages.ml.dataset import (
    FeatureSample,
    TrainingDataset,
    build_dataset,
    extract_samples,
    samples_to_dataset,
)
from packages.ml.model import (
    SignalEdge,
    SignalEdgeModel,
    SignalFeatureWeight,
    model_to_dict,
    train_signal_edge_model,
)

__all__ = [
    "FeatureSample",
    "SignalEdge",
    "SignalEdgeModel",
    "SignalFeatureWeight",
    "TrainingDataset",
    "build_dataset",
    "extract_samples",
    "model_to_dict",
    "samples_to_dataset",
    "train_signal_edge_model",
]
