# DoubleAgent Contracts

Contract testing framework for DoubleAgent services.

## Installation

```bash
pip install doubleagent-contracts
```

## Usage

```python
from doubleagent_contracts import Target, contract_test

@contract_test
def test_something(target: Target, client):
    """Test runs against both fake and real API."""
    result = client.do_something()
    assert result is not None
    
    # Cleanup for real API only
    if target.is_real:
        client.cleanup()
```

## Target

The `Target` class abstracts between fake and real API:

```python
target = Target.from_env(
    service_name="github",
    fake_url="http://localhost:8080",
    real_url="https://api.github.com",
    auth_env_var="GITHUB_TOKEN",
)

# Check target type
if target.is_fake:
    print("Running against DoubleAgent fake")
elif target.is_real:
    print("Running against real API")
```

## Running Tests

```bash
# Against fake (default)
DOUBLEAGENT_TARGET=fake uv run pytest

# Against real API
DOUBLEAGENT_TARGET=real uv run pytest
```
