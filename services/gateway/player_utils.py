"""Player-related utility functions."""

import asyncio
import httpx
from redis.asyncio import Redis


async def _fetch_player_field(
    player_id: int, field_type: str, extractor_fn, redis: Redis = None
) -> str:
    """
    Generic player data fetcher with caching.

    Args:
        player_id: NHL player ID
        field_type: Type of field ('name' or 'headshot') for cache key
        extractor_fn: Function to extract the desired field from API response data
        redis: Redis client for caching

    Returns:
        Extracted field value or None if not found
    """
    if not player_id:
        return None

    # Check Redis cache first if available
    cache_key = f"player_{field_type}:{player_id}"
    if redis:
        cached_value = await redis.get(cache_key)
        if cached_value:
            return cached_value

    try:
        # Use NHL API public endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api-web.nhle.com/v1/player/{player_id}/landing", timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                # Extract the field using the provided extractor function
                value = extractor_fn(data)
                if value:
                    # Cache in Redis if available
                    if redis:
                        await redis.setex(cache_key, 86400, value)  # Cache for 24 hours
                    return value
            elif response.status_code == 404:
                print(f"[gateway] Player {player_id} not found in NHL API")
            else:
                print(
                    f"[gateway] NHL API error {response.status_code} for player {player_id}"
                )
    except httpx.TimeoutException:
        print(f"[gateway] Timeout fetching player {field_type} for {player_id}")
    except Exception as e:
        print(f"[gateway] Error fetching player {field_type} for {player_id}: {e}")

    return None


async def get_player_name(player_id: int, redis: Redis = None) -> str:
    """Get player name from NHL API with Redis caching"""

    def extract_name(data):
        first_name = data.get("firstName", {}).get("default", "")
        last_name = data.get("lastName", {}).get("default", "")
        if first_name and last_name:
            return f"{first_name} {last_name}"
        return None

    return await _fetch_player_field(player_id, "name", extract_name, redis)


async def get_player_headshot(player_id: int, redis: Redis = None) -> str:
    """Get player headshot URL from NHL API with Redis caching"""

    def extract_headshot(data):
        return data.get("headshot", "")

    return await _fetch_player_field(player_id, "headshot", extract_headshot, redis)


async def _fetch_player_field_batch(
    player_ids: list, field_type: str, extractor_fn, redis: Redis = None
) -> dict:
    """
    Generic batch player data fetcher with caching.

    Args:
        player_ids: List of NHL player IDs
        field_type: Type of field ('name' or 'headshot') for cache key
        extractor_fn: Function to extract the desired field from API response data
        redis: Redis client for caching

    Returns:
        Dictionary mapping player_id to extracted field value
    """
    if not player_ids:
        return {}

    # Remove None and duplicates
    unique_ids = list(set([pid for pid in player_ids if pid]))
    if not unique_ids:
        return {}

    # Check Redis cache first (batch read)
    cached_data = {}
    if redis and unique_ids:
        # Batch read from Redis
        keys = [f"player_{field_type}:{pid}" for pid in unique_ids]
        values = await redis.mget(keys)
        for pid, value in zip(unique_ids, values):
            if value:
                cached_data[pid] = value

    # Find missing player IDs
    missing_ids = [pid for pid in unique_ids if pid not in cached_data]

    if not missing_ids:
        return cached_data

    # Fetch missing players in parallel
    async def fetch_player_data(pid):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api-web.nhle.com/v1/player/{pid}/landing", timeout=3.0
                )
                if response.status_code == 200:
                    data = response.json()
                    value = extractor_fn(data)
                    if value:
                        # Cache in Redis
                        if redis:
                            await redis.setex(
                                f"player_{field_type}:{pid}", 86400, value
                            )
                        return pid, value
                elif response.status_code == 404:
                    print(f"[gateway] Player {pid} not found in NHL API")
                else:
                    print(
                        f"[gateway] NHL API error {response.status_code} for player {pid}"
                    )
        except httpx.TimeoutException:
            print(f"[gateway] Timeout fetching player {field_type} {pid}")
        except Exception as e:
            print(f"[gateway] Error fetching player {field_type} {pid}: {e}")
        return pid, None

    # Fetch all missing players in parallel
    tasks = [fetch_player_data(pid) for pid in missing_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results
    for result in results:
        if isinstance(result, Exception):
            print(f"[gateway] Exception in batch {field_type} fetch: {result}")
            continue
        if isinstance(result, tuple):
            pid, value = result
            if value:  # Only add if value was successfully fetched
                cached_data[pid] = value

    return cached_data


async def get_player_names_batch(player_ids: list, redis: Redis = None) -> dict:
    """Batch fetch player names in parallel"""

    def extract_name(data):
        first_name = data.get("firstName", {}).get("default", "")
        last_name = data.get("lastName", {}).get("default", "")
        if first_name and last_name:
            return f"{first_name} {last_name}"
        return None

    return await _fetch_player_field_batch(player_ids, "name", extract_name, redis)


async def get_player_headshots_batch(player_ids: list, redis: Redis = None) -> dict:
    """Batch fetch player headshots in parallel"""

    def extract_headshot(data):
        return data.get("headshot", "")

    return await _fetch_player_field_batch(
        player_ids, "headshot", extract_headshot, redis
    )
