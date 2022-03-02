# The MIT License (MIT)
#
# Copyright (c) 2022- CNRS
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from typing import Any, Callable, Optional

import torch
from torchmetrics import Metric

from pyannote.audio.utils.permutation import permutate


def der_dim_check(preds: torch.Tensor, target: torch.Tensor):
    if len(preds.shape) != 3 or len(target.shape) != 3:
        msg = "Incorrect shape: should be (batch_size, num_frames, num_classes)."
        raise ValueError(msg)

    batch_size, num_samples, num_classes_1 = target.shape
    batch_size_, num_samples_, num_classes_2 = preds.shape
    if (
        batch_size != batch_size_
        or num_samples != num_samples_
        or num_classes_1 != num_classes_2
    ):
        msg = f"Shape mismatch: {tuple(target.shape)} vs. {tuple(preds.shape)}."
        raise ValueError(msg)


def compute_der_values(preds: torch.Tensor, target: torch.Tensor, threshold: float):
    preds_bin = (preds > threshold).float()

    hypothesis, _ = permutate(target, preds_bin)

    detection_error = torch.sum(hypothesis, 2) - torch.sum(target, 2)
    false_alarm = torch.maximum(detection_error, torch.zeros_like(detection_error))
    missed_detection = torch.maximum(
        -detection_error, torch.zeros_like(detection_error)
    )

    confusion = torch.sum((hypothesis != target) * hypothesis, 2) - false_alarm

    false_alarm = torch.sum(false_alarm)
    missed_detection = torch.sum(missed_detection)
    confusion = torch.sum(confusion)
    total = 1.0 * torch.sum(target)
    return false_alarm, missed_detection, confusion, total


class SegmentationMetric(Metric):
    """Implementing this class instead of Metric means (batch,frames,classes)-sized input tensors are expected."""

    def __init__(
        self,
        compute_on_step: bool = True,
        dist_sync_on_step: bool = False,
        process_group: Optional[Any] = None,
        dist_sync_fn: Callable = None,
    ) -> None:
        super().__init__(
            compute_on_step, dist_sync_on_step, process_group, dist_sync_fn
        )


class DiscreteDiarizationErrorRate(SegmentationMetric):
    """Compute diarization error rate on discretized annotations with torchmetrics"""

    def __init__(self, threshold: float = 0.5):
        super().__init__()

        self.threshold = threshold

        self.add_state("false_alarm", default=torch.tensor(0.0), dist_reduce_fx="sum")
        self.add_state(
            "missed_detection", default=torch.tensor(0.0), dist_reduce_fx="sum"
        )
        self.add_state("confusion", default=torch.tensor(0.0), dist_reduce_fx="sum")
        self.add_state("total", default=torch.tensor(0.0), dist_reduce_fx="sum")

    def update(self, preds: torch.Tensor, target: torch.Tensor):
        der_dim_check(preds, target)

        false_alarm, missed_detection, confusion, total = compute_der_values(
            preds, target, self.threshold
        )
        self.false_alarm += false_alarm
        self.missed_detection += missed_detection
        self.confusion += confusion
        self.total += total

    def compute(self):
        return (self.false_alarm + self.missed_detection + self.confusion) / self.total
