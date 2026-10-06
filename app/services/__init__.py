"""Public service interfaces.

The analysis service is loaded lazily so importing the LLM service does not
require the optional analysis service module to be present.
"""

from app.services.llm_service import LLMService

__all__ = ["AnalysisService", "LLMService"]


def __getattr__(name: str):
    if name == "AnalysisService":
        from app.services.analysis_service import AnalysisService

        return AnalysisService

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
