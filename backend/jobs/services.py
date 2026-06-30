import hashlib
import json
import os
import re
import signal
from django.conf import settings
from django.core.cache import cache
from openai import OpenAI
from pyspark.sql import functions as F
from uploads.models import DatasetUpload


class RegexSafetyError(Exception):
    """Raised when a regex pattern may cause catastrophic backtracking."""


class TriageError(Exception):
    """Raised when triage fails to produce valid structured output or references unknown columns."""


_REGEX_SAFETY_TIMEOUT = 2  # seconds
_REGEX_SAFETY_TEST_STRING = "a" * 30  # short string to detect pathological patterns


def _regex_timeout_handler(signum, frame):
    raise RegexSafetyError(
        "Regex pattern timed out during safety check, likely catastrophic backtracking"
    )


class LLMRegexService:
    CACHE_PREFIX = "regex_prompt:"
    CACHE_TTL = 60 * 60 * 24 * 14  # 14 days

    @classmethod
    def validate_regex_safety(cls, pattern: str) -> None:
        """Compile regex and test it against a short string with a timeout.

        Raises ValueError if the pattern is syntactically invalid.
        Raises RegexSafetyError if the pattern triggers catastrophic backtracking.
        """
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Generated regex pattern is invalid: {e}. Pattern was: {pattern}")
        # signal.alarm for timeout; upgrade to per-regex locks if throughput matters
        old_handler = signal.signal(signal.SIGALRM, _regex_timeout_handler)
        signal.alarm(_REGEX_SAFETY_TIMEOUT)
        try:
            compiled.search(_REGEX_SAFETY_TEST_STRING)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    @classmethod
    def get_or_generate_regex(cls, natural_language_prompt: str) -> str:
        prompt_hash = hashlib.sha256(natural_language_prompt.encode()).hexdigest()
        cache_key = f"{cls.CACHE_PREFIX}{prompt_hash}"
        cached_regex = cache.get(cache_key)
        if cached_regex:
            return cached_regex

        api_key = os.environ.get('OPENROUTER_API_KEY', 'mock_key')
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key
        )

        system_prompt = (
            "You are an expert regular expression generator for PySpark data transformations. "
            "Convert the user's natural language pattern description into a precise, highly optimized, "
            "and valid Python/Java compatible regular expression. "
            "Output ONLY the raw regex string. Do not include markdown code blocks, backticks, explanations, or quotes."
        )

        response = client.chat.completions.create(
            model="deepseek/deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": natural_language_prompt}
            ],
            temperature=0.1,
        )

        raw_content = response.choices[0].message.content.strip()

        # Sanitize markdown wrapper if present
        pattern = raw_content
        if pattern.startswith("```"):
            lines = pattern.split("\n")
            if len(lines) >= 2:
                pattern = "\n".join(lines[1:-1]).strip()
            else:
                pattern = pattern.replace("```regex", "").replace("```", "").strip()

        # Validate regex: compilation + backtracking guard
        cls.validate_regex_safety(pattern)

        cache.set(cache_key, pattern, cls.CACHE_TTL)
        return pattern


class TriageService:
    @classmethod
    def triage(cls, natural_language_prompt: str, column_names: list[str]) -> list[dict]:
        """Parse a natural language prompt into structured transformations.

        Calls the LLM with the dataset column names as context, parses the JSON
        response into a list of transformation dicts, and validates that every
        target column exists in the provided schema.

        Args:
            natural_language_prompt: The user's free-text description of what to transform.
            column_names: The dataset's actual column names to validate against.

        Returns:
            A list of dicts, each with keys: column, nl_pattern, replacement.

        Raises:
            TriageError: If the LLM response is not valid JSON, not a list, missing
                         required keys, or references columns not in column_names.
        """
        api_key = os.environ.get('OPENROUTER_API_KEY', 'mock_key')
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key
        )

        system_prompt = (
            "You are an expert data transformation analyst. "
            "Given a natural language prompt and a list of column names from a dataset, "
            "identify which columns the user wants to transform, what pattern to match in each column, "
            "and what replacement value to use (empty string if no replacement is specified). "
            "Respond with ONLY a JSON array of objects. Each object must have exactly three keys: "
            "'column' (string), 'nl_pattern' (string), and 'replacement' (string). "
            "Do not include markdown code blocks, explanations, or any other text. "
            f"The dataset has the following columns: {', '.join(column_names)}."
        )

        response = client.chat.completions.create(
            model="deepseek/deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": natural_language_prompt}
            ],
            temperature=0.1,
        )

        raw_content = response.choices[0].message.content.strip()

        # Sanitize markdown wrapper if present
        pattern_text = raw_content
        if pattern_text.startswith("```"):
            lines = pattern_text.split("\n")
            if len(lines) >= 2:
                pattern_text = "\n".join(lines[1:-1]).strip()
            else:
                pattern_text = pattern_text.replace("```json", "").replace("```", "").strip()

        try:
            transformations = json.loads(pattern_text)
        except json.JSONDecodeError as exc:
            raise TriageError(
                f"Failed to parse LLM response as JSON: {exc}. Response was: {raw_content}"
            )

        if not isinstance(transformations, list):
            raise TriageError(
                f"Expected LLM response to be a JSON array, got {type(transformations).__name__}. "
                f"Response was: {raw_content}"
            )

        for item in transformations:
            if not isinstance(item, dict):
                raise TriageError(
                    f"Expected each transformation to be a dict, got {type(item).__name__}. "
                    f"Response was: {raw_content}"
                )
            if "column" not in item or "nl_pattern" not in item or "replacement" not in item:
                raise TriageError(
                    f"Each transformation must have keys 'column', 'nl_pattern', and 'replacement'. "
                    f"Missing keys in: {item}. Response was: {raw_content}"
                )

        unknown_columns = [
            item["column"] for item in transformations if item["column"] not in column_names
        ]
        if unknown_columns:
            raise TriageError(
                f"Unknown columns referenced in triage: {unknown_columns}"
            )

        return transformations


class SparkProcessingService:
    @classmethod
    def process(cls, parquet_path: str, specs: list[dict], job_id: int,
                progress_callback=None, storage_dir: str | None = None) -> tuple[str, str]:
        from jobs.spark import get_spark_session
        spark = get_spark_session()
        df = spark.read.parquet(parquet_path)
        total = len(specs)

        # Build all regex replacements in a single projection to avoid
        # degenerate Catalyst plans (SPARK-17006).
        exprs = {col: F.col(col) for col in df.columns}
        for i, spec in enumerate(specs, 1):
            exprs[spec["column"]] = F.regexp_replace(
                F.col(spec["column"]), spec["regex"], spec["replacement"]
            )
            if progress_callback and total > 0:
                progress_callback(round(i / total * 100))
        df = df.select(*[expr.alias(col) for col, expr in exprs.items()])

        result_rel = os.path.join("output", str(job_id), "result")
        preview_rel = os.path.join("output", str(job_id), "preview.parquet")
        base = storage_dir or StorageService.get_storage_base_dir()
        output_dir = os.path.join(base, result_rel)

        os.makedirs(output_dir, exist_ok=True)
        df.write.mode("overwrite").parquet(output_dir)

        # Read from written output to avoid re-executing transformations
        spark.read.parquet(output_dir).limit(100) \
            .write.mode("overwrite").parquet(os.path.join(base, preview_rel))

        return result_rel, preview_rel


class StorageService:
    STORAGE_DIR_NAME = "uploads_storage"

    @classmethod
    def get_storage_base_dir(cls) -> str:
        return os.path.join(str(settings.BASE_DIR), cls.STORAGE_DIR_NAME)

    @classmethod
    def resolve_absolute_path(cls, dataset: DatasetUpload) -> str:
        return os.path.join(cls.get_storage_base_dir(), os.path.basename(dataset.file_path))
