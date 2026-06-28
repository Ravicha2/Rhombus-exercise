# Distributed NL-to-Regex Data Processing Platform

An asynchronous web application and distributed transformation engine that enables users to upload large CSV/Excel datasets, specify natural language pattern descriptions, and execute distributed regex replacements at scale without blocking the web request cycle.

## Language

**DatasetUpload**:
A raw CSV or Excel dataset uploaded by a user for asynchronous pattern replacement.
_Avoid_: File, upload, document

**ProcessingJob**:
An asynchronous execution unit tracking the status, task ID, and progress of applying LLM-generated regex transformations across a dataset.
_Avoid_: Task, run, execution, process

## Relationships

- A **DatasetUpload** has one or more **ProcessingJobs**

## Example dialogue

> **Dev:** "When a user submits a natural language prompt, do we pass the **DatasetUpload** binary data directly to the Celery worker?"
> **Domain expert:** "No — the Celery worker fetches the **ProcessingJob**, reads the file path from the associated **DatasetUpload**, and uses PySpark to ingest the file directly from the shared filesystem."

## Flagged ambiguities

- "upload" was used to mean both the binary file and the metadata record — resolved: **DatasetUpload** represents the database metadata record containing the file path.
