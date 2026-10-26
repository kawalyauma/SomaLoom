"""Equation detection and conservative native-text normalization."""
from .equations import EquationAnalysis, analyze_equation, is_equation

__all__ = ["EquationAnalysis", "analyze_equation", "is_equation"]
