"""FlagCov: code coverage for feature flags."""

from flagcov.analyze import Report, analyze
from flagcov.environment import load_document
from flagcov.override import OFF
from flagcov.recorder import Record, recorder

__all__ = ["OFF", "Record", "Report", "analyze", "load_document", "recorder"]
__version__ = "0.1.0"
