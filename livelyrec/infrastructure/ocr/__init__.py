"""OCR エンジンと数字テンプレートマッチング。"""

from .base import OcrEngine
from .digit_template import DigitTemplateRecognizer
from .paddle import PaddleOcrEngine

__all__ = ["OcrEngine", "PaddleOcrEngine", "DigitTemplateRecognizer"]
