# DoubleAgent SDK

Python SDK for running and managing DoubleAgent fake services.

## Installation

```bash
pip install doubleagent
```

## Usage

```python
from doubleagent import DoubleAgent

async def main():
    da = DoubleAgent()
    
    # Start a fake service
    github = await da.start("github", port=8080)
    
    # Use with official SDK
    from github import Github
    client = Github(base_url=github.url, login_or_token="fake-token")
    
    # ... run tests ...
    
    da.stop_all()
```

## pytest Integration

```python
from doubleagent.pytest import github_service

@pytest.fixture
def github():
    with github_service() as gh:
        yield gh

def test_something(github):
    from github import Github
    client = Github(base_url=github.url, login_or_token="fake")
    # ... test code ...
```
