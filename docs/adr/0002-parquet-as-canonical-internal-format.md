# Parquet as Canonical Internal Format

Normalize all uploaded files (CSV, Excel) to Parquet at upload time. PySpark always reads Parquet. The processing pipeline never sees or handles the original format.

## Status

accepted

## Considered Options

- **Convert Excel/CSV to Parquet at upload time, PySpark always reads Parquet**: Normalization happens once, early, in a small contained job. Processing pipeline is format-agnostic.
- **Let PySpark handle all formats natively (spark-excel JAR for Excel, built-in CSV reader)**: No conversion step, but adds format branching in the hot path and requires JAR dependencies for Excel support.
- **Pandas read, then `spark.createDataFrame()`**: Uniform read path, but loads the entire file into memory on every job. Normalization is re-done per job.

## Decision

Convert to Parquet at upload time via an async Celery task. Store the Parquet path on `DatasetUpload`. PySpark always reads Parquet.

## Consequences

- Upload pipeline: validate file, convert to Parquet via pandas, store Parquet path. DatasetUpload gains `status` (UPLOADING, CONVERTING, READY, FAILED) and `parquet_file_path`.
- Processing pipeline: one code path, no format branching. Parquet is columnar, splittable, schema-aware, and faster than CSV.
- Multiple ProcessingJobs on the same DatasetUpload skip re-normalization.
- Column names are read from Parquet schema during normalization and stored as `column_names` JSONField on DatasetUpload, so downstream LLM calls never need file access.