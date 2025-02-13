#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from typing import Any, cast, Dict, List, Optional, Type

import torch
from torchrec.metrics.metrics_namespace import MetricName, MetricNamespace, MetricPrefix
from torchrec.metrics.rec_metric import (
    MetricComputationReport,
    RecMetric,
    RecMetricComputation,
    RecMetricException,
)


ERROR_SUM = "error_sum"
WEIGHTED_NUM_SAMPES = "weighted_num_samples"


def compute_mse(
    error_sum: torch.Tensor, weighted_num_samples: torch.Tensor
) -> torch.Tensor:
    return torch.where(
        weighted_num_samples == 0.0, 0.0, error_sum / weighted_num_samples
    ).double()


def compute_rmse(
    error_sum: torch.Tensor, weighted_num_samples: torch.Tensor
) -> torch.Tensor:
    return torch.where(
        weighted_num_samples == 0.0, 0.0, torch.sqrt(error_sum / weighted_num_samples)
    ).double()


def compute_error_sum(
    labels: torch.Tensor, predictions: torch.Tensor, weights: torch.Tensor
) -> torch.Tensor:
    predictions = predictions.double()
    return torch.sum(weights * torch.square(labels - predictions), dim=-1)


def get_mse_states(
    labels: torch.Tensor, predictions: torch.Tensor, weights: torch.Tensor
) -> torch.Tensor:
    return torch.stack(
        [
            compute_error_sum(labels, predictions, weights),
            torch.sum(weights, dim=-1),
        ]
    )


class MSEMetricComputation(RecMetricComputation):
    r"""
    This class implements the RecMetricComputation for MSE, i.e. Mean Squared Error.

    The constructor arguments are defined in RecMetricComputation.
    See the docstring of RecMetricComputation for more detail.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        state_names = [
            "error_sum",
            "weighted_num_samples",
        ]
        self._add_state(
            state_names,
            torch.zeros((len(state_names), self._n_tasks), dtype=torch.double),
            add_window_state=True,
            dist_reduce_fx="sum",
            persistent=True,
        )

    def update(
        self,
        *,
        predictions: Optional[torch.Tensor],
        labels: torch.Tensor,
        weights: Optional[torch.Tensor],
        **kwargs: Dict[str, Any],
    ) -> None:
        if predictions is None or weights is None:
            raise RecMetricException(
                "Inputs 'predictions' and 'weights' should not be None for MSEMetricComputation update"
            )
        states = get_mse_states(labels, predictions, weights)
        num_samples = predictions.shape[-1]
        state = getattr(self, self._fused_name)
        state += states
        self._aggregate_window_state(self._fused_name, states, num_samples)

    def _compute(self) -> List[MetricComputationReport]:
        return [
            MetricComputationReport(
                name=MetricName.MSE,
                metric_prefix=MetricPrefix.LIFETIME,
                value=compute_mse(
                    self.get_state(ERROR_SUM),
                    self.get_state(WEIGHTED_NUM_SAMPES),
                ),
            ),
            MetricComputationReport(
                name=MetricName.RMSE,
                metric_prefix=MetricPrefix.LIFETIME,
                value=compute_rmse(
                    self.get_state(ERROR_SUM),
                    self.get_state(WEIGHTED_NUM_SAMPES),
                ),
            ),
            MetricComputationReport(
                name=MetricName.MSE,
                metric_prefix=MetricPrefix.WINDOW,
                value=compute_mse(
                    self.get_window_state(ERROR_SUM),
                    self.get_window_state(WEIGHTED_NUM_SAMPES),
                ),
            ),
            MetricComputationReport(
                name=MetricName.RMSE,
                metric_prefix=MetricPrefix.WINDOW,
                value=compute_rmse(
                    self.get_window_state(ERROR_SUM),
                    self.get_window_state(WEIGHTED_NUM_SAMPES),
                ),
            ),
        ]


class MSEMetric(RecMetric):
    _namespace: MetricNamespace = MetricNamespace.MSE
    _computation_class: Type[RecMetricComputation] = MSEMetricComputation
