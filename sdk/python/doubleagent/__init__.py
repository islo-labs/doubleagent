"""
DoubleAgent SDK - Programmatic interface for running fake services.

Usage:
    from doubleagent import DoubleAgent

    async with DoubleAgent() as da:
        github = await da.start("github")
        # Use github.url with official SDK...
        await github.reset()
"""

from .client import DoubleAgent, Service

__all__ = ["DoubleAgent", "Service"]
__version__ = "0.1.0"
