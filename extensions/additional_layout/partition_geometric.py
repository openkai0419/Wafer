from wafer.plugin.layout import BaseLayoutPlugin
from ._partition_base import PartitionCalculatorBase, equal_ratio


class GeometricPartitionCalculator(PartitionCalculatorBase):

    def _split_point(self, count):
        return count // 2

    def _area_ratio(self, sorted_ar, ar_prefix, inv_prefix,
                    start, count, left_count, split_x):
        return equal_ratio(sorted_ar, ar_prefix, inv_prefix,
                           start, count, left_count, split_x)


class GeometricPartitionLayout(BaseLayoutPlugin):
    NAME = 'partitionGeometric'
    DISPLAY_NAME = 'Partition (Geometric)'
    PRIORITY = 84

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        return GeometricPartitionCalculator(
            aspect_ratios, base_size, spacing,
            container_width, container_height, orientation,
        )
