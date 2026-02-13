"""
Target configuration for contract tests.

Controls whether tests run against real API or DoubleAgent fake.
"""

import os
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class Target:
    """
    Represents the target API for contract tests.
    
    Attributes:
        name: "real" or "fake"
        base_url: Base URL of the API
        auth_token: Authentication token (from env var for real API)
        run_id: Unique ID for this test run (for resource naming)
    """
    
    name: str
    base_url: str
    auth_token: Optional[str]
    run_id: str
    
    @property
    def is_real(self) -> bool:
        return self.name == "real"
    
    @property
    def is_fake(self) -> bool:
        return self.name == "fake"
    
    @classmethod
    def from_env(
        cls,
        service_name: str,
        fake_url: str,
        real_url: str,
        auth_env_var: str,
    ) -> "Target":
        """
        Create Target from environment variables.
        
        Set DOUBLEAGENT_TARGET=real|fake to control which target is used.
        Default is "fake".
        """
        target_name = os.environ.get("DOUBLEAGENT_TARGET", "fake")
        
        if target_name == "real":
            auth_token = os.environ.get(auth_env_var)
            if not auth_token:
                raise ValueError(
                    f"Real API target requires {auth_env_var} environment variable"
                )
            return cls(
                name="real",
                base_url=real_url,
                auth_token=auth_token,
                run_id=uuid.uuid4().hex[:8],
            )
        else:
            return cls(
                name="fake",
                base_url=fake_url,
                auth_token="doubleagent-fake-token",
                run_id=uuid.uuid4().hex[:8],
            )
