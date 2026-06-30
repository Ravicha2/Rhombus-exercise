from pyspark.sql import SparkSession


def get_spark_session() -> SparkSession:
    """Return a lazily-created singleton SparkSession configured for local mode."""
    return SparkSession.builder \
        .master("local[*]") \
        .appName("rhombus") \
        .getOrCreate()