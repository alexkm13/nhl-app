"""Player-related utility functions."""
import asyncio
import httpx
from redis.asyncio import Redis


async def get_player_name(player_id: int, redis: Redis = None) -> str:
    """Get player name from NHL API with Redis caching"""
    if not player_id:
        return None
    
    # Check Redis cache first if available
    if redis:
        cached_name = await redis.get(f"player_name:{player_id}")
        if cached_name:
            return cached_name
    
    try:
        # Use NHL API public endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api-web.nhle.com/v1/player/{player_id}/landing",
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                # Extract player name
                first_name = data.get("firstName", {}).get("default", "")
                last_name = data.get("lastName", {}).get("default", "")
                if first_name and last_name:
                    name = f"{first_name} {last_name}"
                    # Cache in Redis if available
                    if redis:
                        await redis.setex(f"player_name:{player_id}", 86400, name)  # Cache for 24 hours
                    return name
            elif response.status_code == 404:
                print(f"[gateway] Player {player_id} not found in NHL API")
            else:
                print(f"[gateway] NHL API error {response.status_code} for player {player_id}")
    except httpx.TimeoutException:
        print(f"[gateway] Timeout fetching player {player_id}")
    except Exception as e:
        print(f"[gateway] Error fetching player {player_id}: {e}")
    
    return None


async def get_player_headshot(player_id: int, redis: Redis = None) -> str:
    """Get player headshot URL from NHL API with Redis caching"""
    if not player_id:
        return None
    
    # Check Redis cache first if available
    if redis:
        cached_headshot = await redis.get(f"player_headshot:{player_id}")
        if cached_headshot:
            return cached_headshot
    
    try:
        # Use NHL API public endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api-web.nhle.com/v1/player/{player_id}/landing",
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                # Extract player headshot URL
                headshot = data.get("headshot", "")
                if headshot:
                    # Cache in Redis if available
                    if redis:
                        await redis.setex(f"player_headshot:{player_id}", 86400, headshot)  # Cache for 24 hours
                    return headshot
            elif response.status_code == 404:
                print(f"[gateway] Player {player_id} not found in NHL API")
            else:
                print(f"[gateway] NHL API error {response.status_code} for player {player_id}")
    except httpx.TimeoutException:
        print(f"[gateway] Timeout fetching player headshot {player_id}")
    except Exception as e:
        print(f"[gateway] Error fetching player headshot {player_id}: {e}")
    
    return None


async def get_player_names_batch(player_ids: list, redis: Redis = None) -> dict:
    """Batch fetch player names in parallel"""
    if not player_ids:
        return {}
    
    # Remove None and duplicates
    unique_ids = list(set([pid for pid in player_ids if pid]))
    if not unique_ids:
        return {}
    
    # Check Redis cache first (batch read)
    cached_names = {}
    if redis and unique_ids:
        # Batch read from Redis
        keys = [f"player_name:{pid}" for pid in unique_ids]
        values = await redis.mget(keys)
        for pid, value in zip(unique_ids, values):
            if value:
                cached_names[pid] = value
    
    # Find missing player IDs
    missing_ids = [pid for pid in unique_ids if pid not in cached_names]
    
    if not missing_ids:
        return cached_names
    
    # Fetch missing players in parallel
    async def fetch_player(pid):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api-web.nhle.com/v1/player/{pid}/landing",
                    timeout=3.0
                )
                if response.status_code == 200:
                    data = response.json()
                    first_name = data.get("firstName", {}).get("default", "")
                    last_name = data.get("lastName", {}).get("default", "")
                    if first_name and last_name:
                        name = f"{first_name} {last_name}"
                        # Cache in Redis
                        if redis:
                            await redis.setex(f"player_name:{pid}", 86400, name)
                        return pid, name
                elif response.status_code == 404:
                    print(f"[gateway] Player {pid} not found in NHL API")
                else:
                    print(f"[gateway] NHL API error {response.status_code} for player {pid}")
        except httpx.TimeoutException:
            print(f"[gateway] Timeout fetching player {pid}")
        except Exception as e:
            print(f"[gateway] Error fetching player {pid}: {e}")
        return pid, None
    
    # Fetch all missing players in parallel
    tasks = [fetch_player(pid) for pid in missing_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Combine results
    for result in results:
        if isinstance(result, Exception):
            print(f"[gateway] Exception in batch player fetch: {result}")
            continue
        if isinstance(result, tuple):
            pid, name = result
            if name:  # Only add if name was successfully fetched
                cached_names[pid] = name
    
    return cached_names


async def get_player_headshots_batch(player_ids: list, redis: Redis = None) -> dict:
    """Batch fetch player headshots in parallel"""
    if not player_ids:
        return {}
    
    # Remove None and duplicates
    unique_ids = list(set([pid for pid in player_ids if pid]))
    if not unique_ids:
        return {}
    
    # Check Redis cache first (batch read)
    cached_headshots = {}
    if redis and unique_ids:
        # Batch read from Redis
        keys = [f"player_headshot:{pid}" for pid in unique_ids]
        values = await redis.mget(keys)
        for pid, value in zip(unique_ids, values):
            if value:
                cached_headshots[pid] = value
    
    # Find missing player IDs
    missing_ids = [pid for pid in unique_ids if pid not in cached_headshots]
    
    if not missing_ids:
        return cached_headshots
    
    # Fetch missing players in parallel
    async def fetch_player_headshot(pid):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api-web.nhle.com/v1/player/{pid}/landing",
                    timeout=3.0
                )
                if response.status_code == 200:
                    data = response.json()
                    headshot = data.get("headshot", "")
                    if headshot:
                        # Cache in Redis
                        if redis:
                            await redis.setex(f"player_headshot:{pid}", 86400, headshot)
                        return pid, headshot
                elif response.status_code == 404:
                    print(f"[gateway] Player {pid} not found in NHL API")
                else:
                    print(f"[gateway] NHL API error {response.status_code} for player {pid}")
        except httpx.TimeoutException:
            print(f"[gateway] Timeout fetching player headshot {pid}")
        except Exception as e:
            print(f"[gateway] Error fetching player headshot {pid}: {e}")
        return pid, None
    
    # Fetch all missing players in parallel
    tasks = [fetch_player_headshot(pid) for pid in missing_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Combine results
    for result in results:
        if isinstance(result, Exception):
            print(f"[gateway] Exception in batch headshot fetch: {result}")
            continue
        if isinstance(result, tuple):
            pid, headshot = result
            if headshot:  # Only add if headshot was successfully fetched
                cached_headshots[pid] = headshot
    
    return cached_headshots

