# PySpark Local Mode with Singleton SparkSession

Run PySpark in local mode inside the Celery worker container with a lazily-initialized singleton SparkSession.

## Status

accepted

## Considered Options

- **PySpark local mode, singleton SparkSession**: Single JVM in the Celery worker process. `SparkSession` created once on first use, reused across tasks. Simplest possible setup.
- **PySpark local mode, per-task SparkSession**: Create and stop a SparkSession per Celery task. Clean state but pays 3-5s JVM startup cost per task.
- **Spark standalone cluster (separate master + worker containers)**: True distributed processing, but significant infrastructure complexity for a single-node Docker Compose setup.

## Decision

Local mode with a singleton SparkSession. `get_spark_session()` lazily creates and caches the session. No custom recycling logic. If memory leaks become real, configure `--max-tasks-per-child` on the Celery worker to recycle the process.

## Consequences

- JVM startup cost is paid once per worker process, not per task.
- The session factory returns the same instance regardless of caller, keeping the extension path open: swap the factory to connect to a remote cluster later without changing call sites.
- Docker container needs sufficient memory (`mem_limit: 2g+`) and a writable `/tmp` for Spark shuffle files.
- No Spark cluster to manage, monitor, or debug. Trade-off: no horizontal scaling beyond adding more Celery workers.