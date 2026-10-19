"""
统计计算工具
"""

from typing import Callable

import numpy as np
import pandas as pd


def _weighted_pearson(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    if len(x) == 0:
        return 0.0
    weights = np.asarray(w, dtype=float)
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 1.0)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    w_sum = weights.sum()
    if w_sum <= 0:
        return 0.0
    wx = np.average(x, weights=weights)
    wy = np.average(y, weights=weights)
    cov = np.average((x - wx) * (y - wy), weights=weights)
    vx = np.average((x - wx) ** 2, weights=weights)
    vy = np.average((y - wy) ** 2, weights=weights)
    denom = float(np.sqrt(vx * vy))
    if denom == 0:
        return 0.0
    return float(cov / denom)


def _weighted_spearman(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    x_rank = pd.Series(x).rank(method="average").to_numpy()
    y_rank = pd.Series(y).rank(method="average").to_numpy()
    return _weighted_pearson(x_rank, y_rank, w)


def _permutation_p_value(
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    corr_func: Callable[[np.ndarray, np.ndarray, np.ndarray], float],
    permutations: int = 200,
    random_seed: int = 42,
) -> float:
    if permutations <= 0 or len(x) < 3:
        return 0.0
    rng = np.random.default_rng(random_seed)
    observed = corr_func(x, y, w)
    extreme = 0
    for _ in range(permutations):
        shuffled = rng.permutation(y)
        if abs(corr_func(x, shuffled, w)) >= abs(observed):
            extreme += 1
    return float((extreme + 1) / (permutations + 1))
