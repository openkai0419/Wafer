import random

from wafer.plugin.layout import BaseLayoutPlugin
from ._partition_base import PartitionCalculatorBase, ar_weighted_ratio


class OrganicPartitionCalculator(PartitionCalculatorBase):

    def __init__(self, aspect_ratios, base_size, spacing,
                 container_width, container_height, orientation):
        super().__init__(aspect_ratios, base_size, spacing,
                         container_width, container_height, orientation)
        self._rng = random.Random(len(aspect_ratios))

    def _split_point(self, count):
        lc = round(max(1, min(count - 1, self._rng.gauss(count / 2, max(1, count / 8)))))
        return max(1, min(count - 1, lc))

    def _area_ratio(self, sorted_ar, ar_prefix, inv_prefix,
                    start, count, left_count, split_x):
        return ar_weighted_ratio(sorted_ar, ar_prefix, inv_prefix,
                                 start, count, left_count, split_x)


class OrganicPartitionLayout(BaseLayoutPlugin):
    NAME = 'partitionOrganic'
    DISPLAY_NAME = 'Partition (Organic)'
    PRIORITY = 85

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        return OrganicPartitionCalculator(
            aspect_ratios, base_size, spacing,
            container_width, container_height, orientation,
        )
