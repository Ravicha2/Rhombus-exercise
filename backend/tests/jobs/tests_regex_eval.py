"""Evaluate generated regexes by calling get_or_generate_regex, then running re.sub against sample input."""
import os
import re
from pathlib import Path
from django.test import TestCase
from django.core.cache import cache
from dotenv import load_dotenv
from jobs.services import LLMRegexService

load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")


class RegexEvalTest(TestCase):
    """Call get_or_generate_regex with a natural language prompt, use the result
    with re.sub against sample input, assert the replacement is correct."""

    def setUp(self):
        if not os.environ.get('OPENROUTER_API_KEY'):
            self.skipTest('OPENROUTER_API_KEY not set — skipping LLM eval test')

    def _eval_regex(self, nl_prompt, replacement, input_text, must_match=True, must_not_match=None):
        """Generate a regex from nl_prompt, apply re.sub, and assert behavior.

        Args:
            nl_prompt: Natural language description for get_or_generate_regex.
            replacement: Replacement string for re.sub.
            input_text: Text to run re.sub against.
            must_match: If True, assert the regex matches and replaces something.
            must_not_match: Optional second input that should NOT be matched.
        """
        cache.clear()
        regex = LLMRegexService.get_or_generate_regex(nl_prompt)
        result = re.sub(regex, replacement, input_text)

        if must_match:
            self.assertNotEqual(
                result, input_text,
                f"Regex {regex!r} from prompt {nl_prompt!r} did not match in: {input_text!r}",
            )
            self.assertIn(replacement, result)

        if must_not_match is not None:
            not_result = re.sub(regex, replacement, must_not_match)
            self.assertEqual(
                not_result, must_not_match,
                f"Regex {regex!r} from prompt {nl_prompt!r} incorrectly matched in: {must_not_match!r}",
            )

    def test_email_regex_eval(self):
        self._eval_regex(
            "email addresses",
            "[REDACTED]",
            "Contact alice@example.com or bob@corp.org for details",
        )

    def test_phone_regex_eval(self):
        self._eval_regex(
            "US phone numbers",
            "[PHONE]",
            "Call 555-867-5309 for details",
        )

    def test_ssn_regex_eval(self):
        self._eval_regex(
            "US Social Security numbers in the format 123-45-6789 appearing within text",
            "[SSN]",
            "SSN: 123-45-6789 on file",
        )

    def test_regex_does_not_over_match(self):
        self._eval_regex(
            "US Social Security numbers in the format 123-45-6789 appearing within text",
            "[SSN]",
            "SSN: 123-45-6789 on file",
            must_not_match="Order number 123-45-678 is not an SSN",
        )

    def test_multi_column_pipeline_eval(self):
        """Full pipeline: triage -> regex generation -> re.sub per column."""
        from jobs.services import TriageService

        cache.clear()
        column_names = ["email", "name", "phone"]
        prompt = "redact all emails and phone numbers"
        transformations = TriageService.triage(prompt, column_names)

        generated_regexes = []
        for t in transformations:
            regex = LLMRegexService.get_or_generate_regex(t["nl_pattern"])
            generated_regexes.append({"column": t["column"], "regex": regex})

        specs = [
            {"column": t["column"], "regex": g["regex"], "replacement": t["replacement"]}
            for t, g in zip(transformations, generated_regexes)
        ]

        rows = [
            {"email": "alice@example.com", "name": "Alice", "phone": "555-123-4567"},
            {"email": "bob@corp.org", "name": "Bob", "phone": "555.999.0000"},
        ]
        for row in rows:
            for spec in specs:
                row[spec["column"]] = re.sub(spec["regex"], spec["replacement"], row[spec["column"]])

        for row in rows:
            self.assertNotIn("@", row["email"], f"Email not fully redacted: {row['email']}")
            self.assertNotIn("555", row["phone"], f"Phone not fully redacted: {row['phone']}")