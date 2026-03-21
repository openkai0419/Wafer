from wafer.plugin.layout import BaseLayoutPlugin
from ._partition_base import PartitionCalculatorBase, ar_weighted_ratio


class OrganicPartitionCalculator(PartitionCalculatorBase):

    def _split_point(self, count):
        return max(1, min(count - 1, count // 2))

    def _area_ratio(self, sorted_ar, ar_prefix, inv_prefix,
                    start, count, left_count, split_x):
        return ar_weighted_ratio(sorted_ar, ar_prefix, inv_prefix,
                                 start, count, left_count, split_x)


class OrganicPartitionLayout(BaseLayoutPlugin):
    NAME = 'ratioPartition'
    DISPLAY_NAME = 'Partition (Aspect)'
    PRIORITY = 85

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        return OrganicPartitionCalculator(
            aspect_ratios, base_size, spacing,
            container_width, container_height, orientation,
        )
