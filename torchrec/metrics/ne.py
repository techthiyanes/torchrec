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


def compute_cross_entropy(
    labels: torch.Tensor,
    predictions: torch.Tensor,
    weights: torch.Tensor,
    eta: float,
) -> torch.Tensor:
    predictions = predictions.double()
    predictions.clamp_(min=eta, max=1 - eta)
    cross_entropy = -weights * labels * torch.log2(predictions) - weights * (
        1.0 - labels
    ) * torch.log2(1.0 - predictions)
    return cross_entropy


def _compute_cross_entropy_norm(
    mean_label: torch.Tensor,
    pos_labels: torch.Tensor,
    neg_labels: torch.Tensor,
    eta: float,
) -> torch.Tensor:
    mean_label = mean_label.double()
    mean_label.clamp_(min=eta, max=1 - eta)
    return -pos_labels * torch.log2(mean_label) - neg_labels * torch.log2(
        1.0 - mean_label
    )


def compute_ne(
    ce_sum: torch.Tensor,
    weighted_num_samples: torch.Tensor,
    pos_labels: torch.Tensor,
    neg_labels: torch.Tensor,
    eta: float,
) -> torch.Tensor:
    mean_label = pos_labels / weighted_num_samples
    ce_norm = _compute_cross_entropy_norm(mean_label, pos_labels, neg_labels, eta)
    return ce_sum / ce_norm


def get_ne_states(
    labels: torch.Tensor, predictions: torch.Tensor, weights: torch.Tensor, eta: float
) -> torch.Tensor:
    cross_entropy = compute_cross_entropy(
        labels,
        predictions,
        weights,
        eta,
    )
    return torch.stack(
        [
            # state "cross_entropy_sum"
            torch.sum(cross_entropy, dim=-1),
            # state "weighted_num_samples"
            torch.sum(weights, dim=-1),
            # state "pos_labels"
            torch.sum(weights * labels, dim=-1),
            # state "neg_labels"
            torch.sum(weights * (1.0 - labels), dim=-1),
        ]
    )


class NEMetricComputation(RecMetricComputation):
    r"""
    This class implements the RecMetricComputation for NE, i.e. Normalized Entropy.

    The constructor arguments are defined in RecMetricComputation.
    See the docstring of RecMetricComputation for more detail.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        state_names = [
            "cross_entropy_sum",
            "weighted_num_samples",
            "pos_labels",
            "neg_labels",
        ]
        self._add_state(
            state_names,
            torch.zeros((len(state_names), self._n_tasks), dtype=torch.double),
            add_window_state=True,
            dist_reduce_fx="sum",
            persistent=True,
        )
        self.eta = 1e-12

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
                "Inputs 'predictions' and 'weights' should not be None for NEMetricComputation update"
            )
        num_samples = predictions.shape[-1]

        states = get_ne_states(labels, predictions, weights, self.eta)
        state = getattr(self, self._fused_name)
        state += states
        self._aggregate_window_state(self._fused_name, states, num_samples)

    def _compute(self) -> List[MetricComputationReport]:
        return [
            MetricComputationReport(
                name=MetricName.NE,
                metric_prefix=MetricPrefix.LIFETIME,
                value=compute_ne(
                    self.get_state("cross_entropy_sum"),
                    self.get_state("weighted_num_samples"),
                    self.get_state("pos_labels"),
                    self.get_state("neg_labels"),
                    self.eta,
                ),
            ),
            MetricComputationReport(
                name=MetricName.NE,
                metric_prefix=MetricPrefix.WINDOW,
                value=compute_ne(
                    self.get_window_state("cross_entropy_sum"),
                    self.get_window_state("weighted_num_samples"),
                    self.get_window_state("pos_labels"),
                    self.get_window_state("neg_labels"),
                    self.eta,
                ),
            ),
        ]


class NEMetric(RecMetric):
    _namespace: MetricNamespace = MetricNamespace.NE
    _computation_class: Type[RecMetricComputation] = NEMetricComputation
