# Two LLM Calls: Triage and Regex Generation

The natural language prompt is processed in two separate LLM calls: a triage call that extracts structured fields (target columns, patterns, replacements) and a regex generation call that produces the actual regex.

## Status

accepted

## Considered Options

- **Two LLM calls (triage then regex generation)**: Triage receives the raw NL prompt plus the dataset's column names, outputs structured `(target_columns, nl_patterns, replacement_values)`. Regex generation receives each `(column, nl_pattern)` pair and produces a regex. Separate concerns, each call has a focused prompt.
- **Single LLM call to extract everything at once**: One prompt asks the LLM to parse columns, patterns, replacements, AND generate regexes. Simpler orchestration, but the prompt is overloaded and error-prone for complex multi-column requests.
- **Structured form input (no triage call)**: User fills separate fields for column, pattern, replacement. No LLM triage needed, but worse UX and defeats the purpose of natural language input.

## Decision

Two LLM calls. Triage first, then per-column regex generation.

## Consequences

- Triage call needs the dataset's column names as context to avoid hallucinating columns that don't exist. Column names come from `DatasetUpload.column_names` (stored during normalization).
- Validation step after triage: reject any column not in the dataset's schema. Fail the job if validation fails.
- Multiple regex generation calls per job (one per target column). Each is independent but a single failure fails the entire job.
- Latency is higher than a single call, but the separation produces more reliable structured output and regex quality.