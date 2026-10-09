"""Media adapter extension point; no dependency on Easel or OpenClaw."""
from .core import MediaError, MediaRuntime, TranscriptionRequest, VideoRequest, OCRRequest, SpeechRequest

__all__ = ["MediaError", "MediaRuntime", "TranscriptionRequest", "VideoRequest", "OCRRequest", "SpeechRequest"]
