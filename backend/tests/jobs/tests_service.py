import json
import os
import tempfile
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from openai import OpenAI
from jobs.services import LLMRegexService, TriageService, TriageError, read_sample_rows, STATIC_TOOLS


class LLMRegexServiceTest(TestCase):

    def setUp(self):
        cache.clear()

    @patch('jobs.services.OpenAI')
    def test_get_or_generate_regex_cached(self, mock_openai_class):
        prompt = "find email addresses"
        expected_regex = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"

        # Setup mock OpenAI client response
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=expected_regex))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        # First call should call LLM and cache
        result1 = LLMRegexService.get_or_generate_regex(prompt)
        self.assertEqual(result1, expected_regex)
        mock_client.chat.completions.create.assert_called_once()

        # Second call should fetch from cache without calling LLM again
        result2 = LLMRegexService.get_or_generate_regex(prompt)
        self.assertEqual(result2, expected_regex)
        self.assertEqual(mock_client.chat.completions.create.call_count, 1)

    @patch('jobs.services.OpenAI')
    def test_regex_sanitization_and_validation(self, mock_openai_class):
        prompt = "find ip addresses"
        raw_llm_output = "```regex\n\\b(?:[0-9]{1,3}\\.){3}[0-9]{1,3}\\b\n```"
        expected_regex = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=raw_llm_output))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = LLMRegexService.get_or_generate_regex(prompt)
        self.assertEqual(result, expected_regex)

    @patch('jobs.services.OpenAI')
    def test_invalid_regex_raises_error(self, mock_openai_class):
        prompt = "invalid prompt"
        invalid_regex = r"([A-Z" # Unclosed parenthesis

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=invalid_regex))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        with self.assertRaises(ValueError) as context:
            LLMRegexService.get_or_generate_regex(prompt)
        self.assertIn("Generated regex pattern is invalid", str(context.exception))


class TriageServiceTest(TestCase):

    @patch('jobs.services.OpenAI')
    def test_triage_single_column(self, mock_openai_class):
        column_names = ["email", "name", "phone"]
        prompt = "redact all emails"
        mock_response_content = '[{"column": "email", "nl_pattern": "redact all emails", "replacement": "[REDACTED]"}]'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=mock_response_content))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = TriageService.triage(prompt, column_names)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["column"], "email")
        self.assertEqual(result[0]["nl_pattern"], "redact all emails")
        self.assertEqual(result[0]["replacement"], "[REDACTED]")
        mock_client.chat.completions.create.assert_called_once()

    @patch('jobs.services.OpenAI')
    def test_triage_multi_column(self, mock_openai_class):
        column_names = ["email", "name", "phone", "address"]
        prompt = "redact emails and phone numbers"
        mock_response_content = (
            '[{"column": "email", "nl_pattern": "redact emails", "replacement": "[EMAIL]"},'
            ' {"column": "phone", "nl_pattern": "redact phone numbers", "replacement": "[PHONE]"}]'
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=mock_response_content))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = TriageService.triage(prompt, column_names)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["column"], "email")
        self.assertEqual(result[1]["column"], "phone")

    @patch('jobs.services.OpenAI')
    def test_triage_unknown_column_raises(self, mock_openai_class):
        column_names = ["email", "name"]
        prompt = "redact all ssns"
        mock_response_content = '[{"column": "ssn", "nl_pattern": "redact all ssns", "replacement": "[REDACTED]"}]'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=mock_response_content))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        with self.assertRaises(TriageError) as context:
            TriageService.triage(prompt, column_names)
        self.assertIn("Unknown columns referenced in triage", str(context.exception))

    @patch('jobs.services.OpenAI')
    def test_triage_malformed_json_raises(self, mock_openai_class):
        column_names = ["email", "name"]
        prompt = "redact all emails"
        mock_response_content = 'not json at all'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=mock_response_content))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        with self.assertRaises(TriageError) as context:
            TriageService.triage(prompt, column_names)
        self.assertIn("Failed to parse LLM response as JSON", str(context.exception))


class TriageJudge:
    """Test fixture: LLM-as-judge evaluator for triage nl_pattern and replacement quality."""

    @classmethod
    def evaluate(cls, actual_pairs: list[dict], expected_pairs: list[dict]) -> dict:
        """Score nl_pattern and replacement similarity between actual and expected.

        Args:
            actual_pairs: List of {nl_pattern, replacement} dicts from real triage output.
            expected_pairs: List of {nl_pattern, replacement} dicts from expected output.

        Returns:
            dict with nl_pattern_score (0-10) and replacement_score (0-10).
        """
        api_key = os.environ.get('OPENROUTER_API_KEY', 'mock_key')
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key
        )
        system_prompt = (
            "You are an expert evaluator of data transformation specifications. "
            "Compare the ACTUAL nl_pattern and replacement values against the EXPECTED ones. "
            "Score: 1) nl_pattern_score — how semantically similar are the pattern descriptions (0-10)? "
            "2) replacement_score — how semantically similar are the replacement values (0-10)? "
            "Respond with ONLY a JSON object with keys: nl_pattern_score (int), replacement_score (int)."
        )
        user_prompt = (
            f"ACTUAL: {json.dumps(actual_pairs)}\n"
            f"EXPECTED: {json.dumps(expected_pairs)}"
        )
        response = client.chat.completions.create(
            model="google/gemini-3.1-flash-lite",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
        )
        raw_content = response.choices[0].message.content.strip()
        text = raw_content
        if text.startswith("```"):
            lines = text.split("\n")
            if len(lines) >= 2:
                text = "\n".join(lines[1:-1]).strip()
            else:
                text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)


class TriageServiceJudgeTest(TestCase):
    """End-to-end eval: real triage LLM call, judge scores nl_pattern/replacement, simple assert on columns."""

    def setUp(self):
        if not os.environ.get('OPENROUTER_API_KEY'):
            self.skipTest('OPENROUTER_API_KEY not set — skipping LLM eval test')

    def test_triage_evaluated_by_llm_judge(self):
        column_names = ["email", "name", "phone"]
        prompt = "replace all email addresses in the email column with [REDACTED]"
        expected_columns = ["email"]
        expected_pairs = [{"nl_pattern": "email addresses", "replacement": "[REDACTED]"}]

        actual = TriageService.triage(prompt, column_names)

        # Simple assertion on columns — no judge needed for exact match
        actual_columns = [t["column"] for t in actual]
        self.assertEqual(sorted(actual_columns), sorted(expected_columns))

        # Judge scores only nl_pattern and replacement pairs
        actual_pairs = [{"nl_pattern": t["nl_pattern"], "replacement": t["replacement"]} for t in actual]
        evaluation = TriageJudge.evaluate(actual_pairs, expected_pairs)

        self.assertGreaterEqual(evaluation["nl_pattern_score"], 5)
        self.assertGreaterEqual(evaluation["replacement_score"], 5)


class ReadSampleRowsTest(TestCase):

    def test_reads_parquet_and_formats_as_table(self):
        import pandas as pd
        df = pd.DataFrame({"email": ["a@b.com", "c@d.com"], "name": ["Alice", "Bob"]})
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name)
            result = read_sample_rows(f.name, n=3)
        os.unlink(f.name)
        self.assertIn("a@b.com", result)
        self.assertIn("Alice", result)

    def test_returns_none_on_missing_file(self):
        result = read_sample_rows("/nonexistent/path.parquet")
        self.assertIsNone(result)

    def test_limits_rows(self):
        import pandas as pd
        df = pd.DataFrame({"x": range(10)})
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name)
            result = read_sample_rows(f.name, n=2)
        os.unlink(f.name)
        # Should have header + 2 data rows, not all 10
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 3)  # header + 2 rows


class LLMRegexServiceSampleDataTest(TestCase):

    def setUp(self):
        cache.clear()

    @patch('jobs.services.OpenAI')
    def test_sample_data_included_in_user_prompt(self, mock_openai_class):
        prompt = "email addresses"
        sample = "email\njohn@example.com"
        expected_regex = r"\b\S+@\S+\.\S+\b"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=expected_regex))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = LLMRegexService.get_or_generate_regex(prompt, sample_data=sample)
        self.assertEqual(result, expected_regex)

        # Verify sample data was included in the user message
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        self.assertIn("john@example.com", user_msg["content"])

    @patch('jobs.services.OpenAI')
    def test_no_sample_data_omits_section(self, mock_openai_class):
        prompt = "email addresses"
        expected_regex = r"\b\S+@\S+\.\S+\b"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=expected_regex))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        LLMRegexService.get_or_generate_regex(prompt)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        self.assertNotIn("sample rows", user_msg["content"])


class TriageServiceSampleDataTest(TestCase):

    @patch('jobs.services.OpenAI')
    def test_sample_data_included_in_system_prompt(self, mock_openai_class):
        column_names = ["email", "city"]
        prompt = "redact emails"
        sample = "email,city\njohn@example.com,New York"
        mock_response_content = '[{"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"}]'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=mock_response_content))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = TriageService.triage(prompt, column_names, sample_data=sample)
        self.assertEqual(len(result), 1)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        self.assertIn("john@example.com", system_msg["content"])
        self.assertIn("New York", system_msg["content"])

    @patch('jobs.services.OpenAI')
    def test_redaction_defaults_to_redacted(self, mock_openai_class):
        """Verify triage prompt instructs LLM to use [REDACTED] for redact/remove/mask."""
        column_names = ["email"]
        prompt = "redact all emails"
        mock_response_content = '[{"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"}]'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=mock_response_content))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = TriageService.triage(prompt, column_names)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        self.assertIn("[REDACTED]", system_msg["content"])


class StaticToolsTest(TestCase):
    """Tests for STATIC_TOOLS dispatch in SparkProcessingService."""

    def test_static_tools_has_expected_keys(self):
        for key in ("truncate", "uppercase", "lowercase", "strip", "fill_nulls"):
            self.assertIn(key, STATIC_TOOLS)

    @patch("jobs.spark.get_spark_session")
    def test_spark_applies_uppercase_tool(self, mock_get_spark):
        from jobs.services import SparkProcessingService
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.master("local[1]").appName("test").getOrCreate()
        mock_get_spark.return_value = spark
        try:
            df = spark.createDataFrame([("alice",), ("BOB",)], ["name"])
            tmp = tempfile.mkdtemp()
            parquet_path = os.path.join(tmp, "input.parquet")
            df.write.mode("overwrite").parquet(parquet_path)

            result_rel, preview_rel = SparkProcessingService.process(
                parquet_path=parquet_path,
                specs=[{"column": "name", "tool": "uppercase"}],
                job_id=9999,
                storage_dir=tmp,
            )
            result_df = spark.read.parquet(os.path.join(tmp, result_rel))
            rows = [r["name"] for r in result_df.collect()]
            self.assertEqual(rows, ["ALICE", "BOB"])
        finally:
            spark.stop()

    @patch("jobs.spark.get_spark_session")
    def test_spark_mixed_static_and_regex(self, mock_get_spark):
        from jobs.services import SparkProcessingService
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.master("local[1]").appName("test").getOrCreate()
        mock_get_spark.return_value = spark
        try:
            df = spark.createDataFrame([("  alice  ", "john@example.com")], ["name", "email"])
            tmp = tempfile.mkdtemp()
            parquet_path = os.path.join(tmp, "input.parquet")
            df.write.mode("overwrite").parquet(parquet_path)

            result_rel, preview_rel = SparkProcessingService.process(
                parquet_path=parquet_path,
                specs=[
                    {"column": "name", "tool": "strip"},
                    {"column": "email", "regex": r"\S+@\S+\.\S+", "replacement": "[REDACTED]"},
                ],
                job_id=9998,
                storage_dir=tmp,
            )
            result_df = spark.read.parquet(os.path.join(tmp, result_rel))
            row = result_df.collect()[0]
            self.assertEqual(row["name"], "alice")
            self.assertEqual(row["email"], "[REDACTED]")
        finally:
            spark.stop()


class TriageStaticToolsPromptTest(TestCase):
    """Verify the triage prompt includes static tool routing instructions."""

    @patch('jobs.services.OpenAI')
    def test_prompt_mentions_static_tools(self, mock_openai_class):
        column_names = ["email", "name"]
        prompt = "truncate the name column"
        mock_response_content = '[{"column": "name", "nl_pattern": "truncate names", "replacement": "truncate"}]'

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=mock_response_content))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        TriageService.triage(prompt, column_names)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        self.assertIn("truncate", system_msg["content"])
        self.assertIn("uppercase", system_msg["content"])
        self.assertIn("lowercase", system_msg["content"])
        self.assertIn("strip", system_msg["content"])
        self.assertIn("fill_nulls", system_msg["content"])
