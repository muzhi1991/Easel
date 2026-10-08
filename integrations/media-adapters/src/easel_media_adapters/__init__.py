"""Media adapter extension point; no dependency on Easel or OpenClaw."""
from .core import MediaError, MediaRuntime, TranscriptionRequest

__all__ = ["MediaError", "MediaRuntime", "TranscriptionRequest"]
