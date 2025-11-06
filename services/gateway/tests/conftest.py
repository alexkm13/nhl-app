"""Shared pytest fixtures for testing."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from main import app


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock(spec=Redis)
    redis.get = AsyncMock(return_value=None)
    redis.hget = AsyncMock(return_value=None)
    redis.hgetall = AsyncMock(return_value={})
    redis.setex = AsyncMock(return_value=True)
    redis.hset = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=True)
    redis.xadd = AsyncMock(return_value="stream-id")
    redis.pubsub = MagicMock()
    redis.decode_responses = True
    return redis


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx client."""
    with patch('httpx.AsyncClient') as mock_client:
        client_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = client_instance
        mock_client.return_value.__aexit__.return_value = None
        yield client_instance


@pytest.fixture
def test_client():
    """Create a FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def sample_game_data():
    """Sample game data from NHL API."""
    return {
        "gameState": "LIVE",
        "startTimeUTC": "2024-01-15T19:00:00Z",
        "homeTeam": {
            "id": 1,
            "commonName": {"default": "Bruins"},
            "placeName": {"default": "Boston"},
            "abbrev": "BOS",
            "logo": "https://example.com/bruins.png",
            "score": 2
        },
        "awayTeam": {
            "id": 2,
            "commonName": {"default": "Leafs"},
            "placeName": {"default": "Toronto"},
            "abbrev": "TOR",
            "logo": "https://example.com/leafs.png",
            "score": 1
        },
        "plays": [
            {
                "typeCode": 505,
                "eventId": "1",
                "timeInPeriod": "15:30",
                "periodDescriptor": {"number": 1},
                "situationCode": "1551",
                "details": {
                    "eventOwnerTeamId": 1,
                    "scoringPlayerId": 12345,
                    "shotType": "wrist",
                    "xCoord": 50,
                    "yCoord": 20
                }
            }
        ]
    }


@pytest.fixture
def sample_boxscore_data():
    """Sample boxscore data from NHL API."""
    return {
        "homeTeam": {
            "id": 1,
            "commonName": {"default": "Bruins"},
            "abbrev": "BOS",
            "logo": "https://example.com/bruins.png",
            "score": 2,
            "sog": 25,
            "roster": {
                "roster": [
                    {
                        "playerId": 12345,
                        "firstName": {"default": "Brad"},
                        "lastName": {"default": "Marchand"},
                        "position": "LW",
                        "sweaterNumber": 63
                    }
                ]
            }
        },
        "awayTeam": {
            "id": 2,
            "commonName": {"default": "Leafs"},
            "abbrev": "TOR",
            "logo": "https://example.com/leafs.png",
            "score": 1,
            "sog": 20,
            "roster": {
                "roster": [
                    {
                        "playerId": 67890,
                        "firstName": {"default": "Auston"},
                        "lastName": {"default": "Matthews"},
                        "position": "C",
                        "sweaterNumber": 34
                    }
                ]
            }
        },
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [
                    {
                        "playerId": 12345,
                        "name": {"default": "Brad Marchand"},
                        "position": "LW",
                        "points": 2,
                        "goals": 1,
                        "assists": 1,
                        "plusMinus": 1,
                        "pim": 0,
                        "shots": 5,
                        "hits": 3,
                        "toi": 1200
                    }
                ],
                "defense": [],
                "goalies": []
            },
            "awayTeam": {
                "forwards": [
                    {
                        "playerId": 67890,
                        "name": {"default": "Auston Matthews"},
                        "position": "C",
                        "points": 1,
                        "goals": 1,
                        "assists": 0,
                        "plusMinus": -1,
                        "pim": 0,
                        "shots": 6,
                        "hits": 2,
                        "toi": 1100
                    }
                ],
                "defense": [],
                "goalies": []
            }
        }
    }

