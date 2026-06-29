from django.test import TestCase
from jobs.services import LLMRegexService, RegexSafetyError


class RegexSafetyTest(TestCase):

    def test_safe_regex_passes_validation(self):
        # Should not raise
        LLMRegexService.validate_regex_safety(r"\b\d{1,3}\b")

    def test_safe_complex_regex_passes(self):
        LLMRegexService.validate_regex_safety(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
        )

    def test_catastrophic_backtracking_regex_times_out(self):
        # (a+)+b on all-'a' string forces exponential backtracking (no 'b' to match)
        pattern = r"(a+)+b"
        with self.assertRaises(RegexSafetyError):
            LLMRegexService.validate_regex_safety(pattern)

    def test_nested_quantifier_backtracking(self):
        # Another pathological pattern: (a|a)* on repeated 'a's
        pattern = r"(a|a)*b"
        with self.assertRaises(RegexSafetyError):
            LLMRegexService.validate_regex_safety(pattern)

    def test_invalid_regex_still_raises_value_error(self):
        with self.assertRaises(ValueError):
            LLMRegexService.validate_regex_safety(r"([A-Z")