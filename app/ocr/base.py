"""OCR strategy interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from PIL import Image


class BaseOCREngine(ABC):
    label: str

    @abstractmethod
    def extract_text(self, image: Image.Image) -> str:
        """Extract text from a Pillow image or raise a useful RuntimeError."""
