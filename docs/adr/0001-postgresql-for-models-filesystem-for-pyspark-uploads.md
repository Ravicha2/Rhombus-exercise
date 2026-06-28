# PostgreSQL for Relational Models and Filesystem for PySpark Uploads

We decided to use PostgreSQL for Django relational models (`DatasetUpload`, `ProcessingJob`) to ensure robust concurrency, while keeping the filesystem (`upload/` folder via shared Docker volume) for raw dataset files so PySpark can ingest them directly and efficiently.

## Status

accepted

## Considered Options

- **PostgreSQL for both models and file storage (`bytea` binary field)**: Rejected due to severe database bloat, a hard 1GB column limit, and PySpark's inability to stream directly from a database blob without writing temporary files to disk.
- **SQLite for models and filesystem for uploads**: Rejected because SQLite suffers from database locking (`OperationalError: database is locked`) during concurrent status and progress updates from Celery workers and Django web views.

## Consequences

- **Concurrency**: Celery workers and Django web views can reliably perform concurrent read/write operations on `ProcessingJob` statuses and progress percentages.
- **Performance**: PySpark can utilize native distributed file loaders (`spark.read.csv`, `spark.read.format('com.crealytics.spark.excel')`) directly against the local filesystem.
- **Infrastructure**: Requires adding a PostgreSQL service to `docker-compose.yml` and managing database/filesystem backup synchronization separately.
