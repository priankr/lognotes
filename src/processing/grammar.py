import ollama
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Valid Ollama model name: starts with alphanumeric, followed by alphanumeric/dots/colons/hyphens
_MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*$")
_MAX_INPUT_LENGTH = 10000

# Instructions live in the system prompt; user text is the entire user prompt.
# This is true structural isolation — the model processes them in separate roles
# so the user text cannot be interpreted as instructions regardless of content.
_SYSTEM_PROMPT = (
    "Fix the grammar and punctuation of transcribed speech. "
    "Do not change the meaning or add new information. "
    "Do not add any explanations or comments. "
    "Only output the corrected text, nothing else."
)


class GrammarProcessor:
    """Processes transcribed text through Ollama for grammar cleanup."""

    def __init__(self, model: str = "llama3.2:1b", host: Optional[str] = None):
        """Initialize grammar processor.

        Args:
            model: Ollama model to use for grammar processing
            host: Ollama server URL. Defaults to the client library's default
                (http://localhost:11434), or the OLLAMA_HOST env var if set.
        """
        self.model = model
        self.host = host
        self._client: Optional[ollama.Client] = None

    def _get_client(self) -> ollama.Client:
        """Get or create Ollama client."""
        if self._client is None:
            self._client = ollama.Client(host=self.host) if self.host else ollama.Client()
        return self._client

    def cleanup(self, text: str) -> str:
        """Clean up grammar and punctuation in transcribed text.

        Args:
            text: Raw transcribed text

        Returns:
            Text with grammar and punctuation fixed
        """
        if not text or not text.strip():
            return text

        try:
            client = self._get_client()
            prompt_text = text[:_MAX_INPUT_LENGTH] if len(text) > _MAX_INPUT_LENGTH else text
            response = client.generate(
                model=self.model,
                system=_SYSTEM_PROMPT,
                prompt=prompt_text,
                options={
                    "temperature": 0.1,  # Low temperature for consistent output
                    "num_predict": len(text) * 2,  # Reasonable output limit
                }
            )
            cleaned = response.get("response", "").strip()

            # Fallback to original if response is empty or much longer
            if not cleaned or len(cleaned) > len(text) * 3:
                return text

            return cleaned

        except Exception as e:
            logger.error(f"Grammar processing failed: {e}")
            return text  # Return original on error

    def is_available(self) -> bool:
        """Check if Ollama is available and model is loaded.

        Returns:
            True if Ollama is running and model is accessible
        """
        try:
            client = self._get_client()
            models = client.list()
            model_names = [m.get("name", "") for m in models.get("models", [])]
            # Check if our model is available (handle tag variations)
            return any(self.model in name or name in self.model for name in model_names)
        except Exception:
            return False

    def change_model(self, model: str) -> None:
        """Change the Ollama model.

        Args:
            model: New model name to use

        Raises:
            ValueError: If the model name fails the allowed-name check.
        """
        if not model or not _MODEL_PATTERN.match(model) or len(model) > 100:
            raise ValueError(f"Invalid Ollama model name: {model!r}")
        self.model = model
