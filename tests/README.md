# Testing Guide

This directory contains automated tests for the NHL app.

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── integration/             # Integration tests
│   └── test_api_integration.py
└── services/               # Service-specific tests
    ├── gateway/
    │   ├── test_main.py           # Gateway service tests
    │   ├── test_utils.py           # Utility function tests
    │   ├── test_probability_model.py  # Probability model tests
    │   ├── test_graph.py           # Graph generation tests
    │   ├── test_feed.py             # Feed rendering tests
    │   ├── test_graph_frontend.js   # Frontend graph JS tests
    │   └── test_feed_frontend.js   # Frontend feed JS tests
    ├── model_svc/
    │   └── test_feature_engineer.py
    ├── ingestor/
    └── feature_state/
```

## Running Tests

```bash
# Run all tests
make test

# Run only unit tests
make test-unit

# Run only integration tests
make test-integration

# Run API endpoint tests
make test-api

# Run with coverage report
make test-cov

# Watch mode (auto-rerun on file changes)
make test-watch
```

## Test Categories

- **Unit tests** (`@pytest.mark.unit`): Test individual functions and components
  - Probability model calculations
  - Graph data processing
  - Feed event processing
- **Integration tests** (`@pytest.mark.integration`): Test API endpoints and service interactions
  - Graph API endpoints
  - Feed API endpoints
  - End-to-end functionality
- **API tests** (`@pytest.mark.api`): Test REST API endpoints
- **Slow tests** (`@pytest.mark.slow`): Tests that may take longer (network calls, etc.)

## Test Coverage

### Probability Model Tests
- ✅ Final game scenarios (home win, away win, tie)
- ✅ Live game scenarios (tied, leading, trailing)
- ✅ Time-based probability adjustments
- ✅ Overtime and shootout handling
- ✅ Edge cases (invalid inputs, negative scores)

### Graph Tests
- ✅ Graph data structure validation
- ✅ Time range calculations
- ✅ Probability to coordinate conversion
- ✅ Interpolation logic
- ✅ API endpoint integration

### Feed Tests
- ✅ Event structure validation
- ✅ Event filtering (crucial vs non-crucial)
- ✅ Event deduplication
- ✅ Event sorting
- ✅ Period grouping
- ✅ API endpoint integration

## Writing Tests

Example test structure:

```python
import pytest

@pytest.mark.unit
class TestMyFunction:
    """Test my function."""
    
    def test_basic_case(self):
        """Test basic functionality."""
        result = my_function("input")
        assert result == "expected"
    
    def test_edge_case(self):
        """Test edge case."""
        result = my_function("")
        assert result is None
```

## Coverage

Current coverage target: 80%+

View coverage report:
```bash
make test-cov
# Open htmlcov/index.html in browser
```

