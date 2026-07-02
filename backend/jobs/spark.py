import os
from pyspark.sql import SparkSession


def get_spark_session() -> SparkSession:
    """Return a lazily-created singleton SparkSession."""
    return SparkSession.builder \
        .master(os.getenv("SPARK_MASTER", "local[*]")) \
        .appName("rhombus") \
        .getOrCreate()