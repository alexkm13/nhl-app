"""Tests for player utility functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from player_utils import (
    get_player_headshot,
    get_player_headshots_batch,
    get_player_name,
    get_player_names_batch,
)


@pytest.mark.asyncio
async def test_get_player_name_success(mock_redis):
    """Test successful player name fetch."""
    player_id = 12345
    expected_name = "Brad Marchand"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "firstName": {"default": "Brad"},
        "lastName": {"default": "Marchand"},
    }

    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return mock_response

    with patch("player_utils.httpx.AsyncClient", MockAsyncClient):
        result = await get_player_name(player_id, mock_redis)

        assert result == expected_name
        mock_redis.setex.assert_called_once()  # Should cache the result


@pytest.mark.asyncio
async def test_get_player_name_cache_hit(mock_redis):
    """Test player name fetch with cache hit."""
    player_id = 12345
    cached_name = "Brad Marchand"
    mock_redis.get.return_value = cached_name

    result = await get_player_name(player_id, mock_redis)

    assert result == cached_name
    mock_redis.setex.assert_not_called()  # Should not cache again


@pytest.mark.asyncio
async def test_get_player_name_not_found(mock_redis):
    """Test player name fetch with 404 error."""
    player_id = 99999

    with patch("player_utils.httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_client.return_value.__aenter__.return_value.get.return_value = (
            mock_response
        )

        result = await get_player_name(player_id, mock_redis)

        assert result is None


@pytest.mark.asyncio
async def test_get_player_name_no_player_id(mock_redis):
    """Test player name fetch with None player_id."""
    result = await get_player_name(None, mock_redis)

    assert result is None
    mock_redis.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_player_name_timeout(mock_redis):
    """Test player name fetch with timeout."""
    player_id = 12345

    with patch("player_utils.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = (
            httpx.TimeoutException("Timeout")
        )

        result = await get_player_name(player_id, mock_redis)

        assert result is None


@pytest.mark.asyncio
async def test_get_player_headshot_success(mock_redis):
    """Test successful player headshot fetch."""
    player_id = 12345
    expected_headshot = "https://example.com/headshot.png"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"headshot": expected_headshot}

    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return mock_response

    with patch("player_utils.httpx.AsyncClient", MockAsyncClient):
        result = await get_player_headshot(player_id, mock_redis)

        assert result == expected_headshot
        mock_redis.setex.assert_called_once()  # Should cache the result


@pytest.mark.asyncio
async def test_get_player_headshot_cache_hit(mock_redis):
    """Test player headshot fetch with cache hit."""
    player_id = 12345
    cached_headshot = "https://example.com/headshot.png"
    mock_redis.get.return_value = cached_headshot

    result = await get_player_headshot(player_id, mock_redis)

    assert result == cached_headshot
    mock_redis.setex.assert_not_called()  # Should not cache again


@pytest.mark.asyncio
async def test_get_player_names_batch(mock_redis):
    """Test batch player names fetch."""
    player_ids = [12345, 67890]

    # Mock mget to return None for both (cache miss)
    mock_redis.mget = AsyncMock(return_value=[None, None])

    # Mock response data
    mock_response_1 = MagicMock()
    mock_response_1.status_code = 200
    mock_response_1.json.return_value = {
        "firstName": {"default": "Brad"},
        "lastName": {"default": "Marchand"},
    }

    mock_response_2 = MagicMock()
    mock_response_2.status_code = 200
    mock_response_2.json.return_value = {
        "firstName": {"default": "Auston"},
        "lastName": {"default": "Matthews"},
    }

    # Create async context manager mock that works with nested calls
    call_count = [0]

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_response_1
            else:
                return mock_response_2

    with patch("player_utils.httpx.AsyncClient", MockAsyncClient):
        result = await get_player_names_batch(player_ids, mock_redis)

        assert len(result) == 2
        assert result[12345] == "Brad Marchand"
        assert result[67890] == "Auston Matthews"


@pytest.mark.asyncio
async def test_get_player_headshots_batch(mock_redis):
    """Test batch player headshots fetch."""
    player_ids = [12345, 67890]

    # Mock mget to return None for both (cache miss)
    mock_redis.mget = AsyncMock(return_value=[None, None])

    # Mock response data
    mock_response_1 = MagicMock()
    mock_response_1.status_code = 200
    mock_response_1.json.return_value = {"headshot": "https://example.com/marchand.png"}

    mock_response_2 = MagicMock()
    mock_response_2.status_code = 200
    mock_response_2.json.return_value = {"headshot": "https://example.com/matthews.png"}

    # Create async context manager mock that works with nested calls
    call_count = [0]

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_response_1
            else:
                return mock_response_2

    with patch("player_utils.httpx.AsyncClient", MockAsyncClient):
        result = await get_player_headshots_batch(player_ids, mock_redis)

        assert len(result) == 2
        assert result[12345] == "https://example.com/marchand.png"
        assert result[67890] == "https://example.com/matthews.png"


@pytest.mark.asyncio
async def test_get_player_names_batch_empty_list(mock_redis):
    """Test batch player names fetch with empty list."""
    result = await get_player_names_batch([], mock_redis)

    assert result == {}


@pytest.mark.asyncio
async def test_get_player_headshots_batch_empty_list(mock_redis):
    """Test batch player headshots fetch with empty list."""
    result = await get_player_headshots_batch([], mock_redis)

    assert result == {}
