import hashlib
import os
import re
from django.conf import settings
from django.core.cache import cache
from openai import OpenAI
from uploads.models import DatasetUpload


class LLMRegexService:
    CACHE_PREFIX = "regex_prompt:"
    CACHE_TTL = 60 * 60 * 24 * 14  # 14 days

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

        # Validate regex compilation
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Generated regex pattern is invalid: {e}. Pattern was: {pattern}")

        cache.set(cache_key, pattern, cls.CACHE_TTL)
        return pattern


class StorageService:
    STORAGE_DIR_NAME = "uploads_storage"

    @classmethod
    def resolve_absolute_path(cls, dataset: DatasetUpload) -> str:
        storage_dir = os.path.join(str(settings.BASE_DIR), cls.STORAGE_DIR_NAME)
        return os.path.join(storage_dir, os.path.basename(dataset.file_path))
