"""
DoubleAgent Contract Testing Framework

This framework enables writing tests that run against both real APIs
and DoubleAgent fakes, validating fidelity.

Usage:
    from doubleagent_contracts import contract_test, Target
    
    @contract_test
    class TestIssues:
        def test_create_issue(self, github_client, target: Target):
            # This test runs against both real GitHub and DoubleAgent fake
            issue = github_client.create_issue(...)
"""

from .target import Target
from .decorators import contract_test

__all__ = ["Target", "contract_test"]
