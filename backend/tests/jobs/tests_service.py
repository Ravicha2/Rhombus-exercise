from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from jobs.services import LLMRegexService


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
