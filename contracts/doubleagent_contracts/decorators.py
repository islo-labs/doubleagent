"""
Decorators for contract tests.
"""

from typing import Type


def contract_test(cls: Type) -> Type:
    """
    Mark a test class as a contract test.

    Contract tests are designed to run against both real APIs and
    DoubleAgent fakes. The test should pass against both targets.

    Usage:
        @contract_test
        class TestIssues:
            def test_create_issue(self, github_client, target):
                # Test code that works with both real and fake
                pass

    The decorator adds markers and documentation to the test class.
    """
    # Add pytest marker
    import pytest

    cls = pytest.mark.contract(cls)

    # Update docstring
    original_doc = cls.__doc__ or ""
    cls.__doc__ = f"""Contract Test: {cls.__name__}

This test runs against both real API and DoubleAgent fake.
Set DOUBLEAGENT_TARGET=real|fake to control the target.

{original_doc}
"""

    return cls
