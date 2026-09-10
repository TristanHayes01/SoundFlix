"""Concrete OCR strategies. Imports are deferred so unused engines cost nothing."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import numpy as np
from PIL import Image, ImageOps
from .base import BaseOCREngine


def _prepared(image: Image.Image) -> Image.Image:
    """Upscale and contrast-normalize flyers before either OCR engine sees them."""
    image = ImageOps.exif_transpose(image).convert("L")
    image = ImageOps.autocontrast(image)
    return image.resize((image.width * 2, image.height * 2))


def _find_tesseract() -> str | None:
    """Find a Windows installation even when its installer did not update PATH."""
    candidates = [
        os.getenv("TESSERACT_CMD"),  # Explicit local override wins.
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
    ]
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


class TesseractEngine(BaseOCREngine):
    label = "Tesseract OCR (system install)"

    def extract_text(self, image: Image.Image) -> str:
        try:
            import pytesseract
            executable = _find_tesseract()
            if not executable:
                raise RuntimeError(
                    "Tesseract was not found. Set TESSERACT_CMD to tesseract.exe or choose Built-in OCR."
                )
            # pytesseract does not discover Program Files automatically on many Windows setups.
            pytesseract.pytesseract.tesseract_cmd = executable
            return pytesseract.image_to_string(_prepared(image), config="--oem 3 --psm 6")
        except pytesseract.TesseractNotFoundError as error:
            raise RuntimeError("Tesseract was not found. Set TESSERACT_CMD or choose Built-in OCR.") from error


class BuiltInOCREngine(BaseOCREngine):
    label = "Built-in OCR (EasyOCR)"

    def __init__(self) -> None:
        self._reader = None

    def extract_text(self, image: Image.Image) -> str:
        try:
            import easyocr
            if self._reader is None:
                # GPU=False makes this work on a normal Windows desktop.
                self._reader = easyocr.Reader(["en"], gpu=False)
            rows = self._reader.readtext(np.array(_prepared(image)), detail=0, paragraph=False)
            return "\n".join(rows)
        except ImportError as error:
            raise RuntimeError("EasyOCR is not installed. Run: pip install -r requirements.txt") from error
