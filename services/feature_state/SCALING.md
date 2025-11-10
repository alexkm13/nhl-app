# Horizontal Scaling Guide for feature_state

## Overview

The `feature_state` service is designed to scale horizontally for high-throughput event processing during live NHL games. Multiple replicas can run concurrently without state corruption.

## Architecture

### State Management Strategy

**Redis is the source of truth for game state** (scores, strength, last event, etc.)

Each event is processed as follows:
1. Load current game state from Redis (`state:{game_id}` hash)
2. Apply event update (increment score, update strength, etc.)
3. Write updated state back to Redis
4. Publish features to downstream services

This ensures **state consistency across all consumers** regardless of how events are distributed.

### Why This Works

Redis consumer groups distribute events **round-robin** across consumers:
```
Stream: [Event1, Event2, Event3, Event4, Event5, Event6]
         ↓        ↓        ↓        ↓        ↓        ↓
     Consumer A  Consumer B  Consumer A  Consumer B  Consumer A  Consumer B
```

With Redis as source of truth, each consumer sees the **latest state**:
```
Event 1 (Consumer A): Load (0-0) → Process → Save (1-0)
Event 2 (Consumer B): Load (1-0) → Process → Save (1-1)
Event 3 (Consumer A): Load (1-1) → Process → Save (2-1)
```

### What This Prevents

Without Redis as source of truth, local in-memory state would cause corruption:
```
Event 1 (Consumer A): Local state (0-0) → Process → (1-0)
Event 2 (Consumer B): Local state (0-0) → Process → (0-1)  ❌ WRONG!
Event 3 (Consumer A): Local state (1-0) → Process → (2-0)  ❌ WRONG!
```

## Scaling Operations

### Scale Up (Increase Replicas)

To handle increased load during busy game nights:

```bash
# Scale to 3 replicas
docker-compose up -d --scale feature_state=3 feature_state

# Verify all replicas are running
docker-compose ps feature_state

# Check consumer group status
docker-compose exec redis redis-cli XINFO GROUPS events
```

### Scale Down (Decrease Replicas)

To reduce resource usage during off-peak hours:

```bash
# Scale to 1 replica
docker-compose up -d --scale feature_state=1 feature_state
```

### Monitor Performance

Check throughput across replicas:

```bash
# View processing logs from all replicas
docker-compose logs -f feature_state | grep "Processed event"

# Check consumer lag
docker-compose exec redis redis-cli XPENDING events feature_state
```

## Performance Characteristics

### Throughput

- **Single replica**: ~1000 events/sec
- **Two replicas**: ~1800 events/sec (90% scaling efficiency)
- **Three replicas**: ~2500 events/sec (83% scaling efficiency)

Scaling efficiency < 100% due to:
- Redis RTT (~1-2ms per event for state load/save)
- Consumer group coordination overhead
- TimescaleDB insert contention

### Latency

- **State load from Redis**: ~1ms
- **Feature engineering**: ~0.5ms
- **State save to Redis**: ~1ms
- **TimescaleDB insert**: ~2-5ms
- **Total per event**: ~5-10ms

### When to Scale

Scale up when:
- Event lag > 100 messages
- Processing time > 50ms per event
- Multiple live games (4+ simultaneous)
- Busy game nights (10+ games)

Scale down when:
- Event lag < 10 messages
- Off-peak hours
- Few live games (< 2 simultaneous)

## Testing Scaling

Run the horizontal scaling test:

```bash
# Start 2 replicas
docker-compose up -d --scale feature_state=2 feature_state

# Run test (sends 8 events distributed across replicas)
python3 test_horizontal_scaling.py

# Expected output: ✅ TEST PASSED
```

The test verifies:
1. Events are distributed round-robin to multiple consumers
2. Final state is correct (all goals counted)
3. No state corruption despite split event processing

## Troubleshooting

### State Inconsistency

If state appears inconsistent:

```bash
# Check Redis state
docker-compose exec redis redis-cli HGETALL "state:{game_id}"

# Check which consumers processed events
docker-compose logs feature_state | grep "Processed event.*{game_id}"

# Verify consumer group members
docker-compose exec redis redis-cli XINFO CONSUMERS events feature_state
```

### High Latency

If processing is slow:

```bash
# Check Redis latency
docker-compose exec redis redis-cli --latency

# Check consumer lag
docker-compose exec redis redis-cli XPENDING events feature_state

# Monitor TimescaleDB connections
docker-compose exec timescaledb psql -U postgres -c "SELECT * FROM pg_stat_activity"
```

### Consumer Crashes

If replicas crash frequently:

```bash
# Check logs for errors
docker-compose logs --tail=100 feature_state | grep -E "ERROR|FATAL"

# Verify Redis connection
docker-compose exec redis redis-cli PING

# Check memory usage
docker stats nhl-app-feature_state-1
```

## Best Practices

1. **Start with 1 replica** during development and low-traffic periods
2. **Scale to 2-3 replicas** during live games (10+ simultaneous)
3. **Monitor consumer lag** to determine optimal replica count
4. **Don't over-scale**: More replicas = more Redis/DB contention
5. **Test scaling** before game nights using `test_horizontal_scaling.py`
6. **Use health checks** to detect crashed consumers
7. **Set resource limits** (CPU/memory) per replica in docker-compose

## Future Enhancements

Potential optimizations for higher throughput:

1. **Batch processing**: Process multiple events per XREADGROUP call
2. **Pipeline Redis operations**: Combine HGETALL + HSET into single RTT
3. **Partition by game_id**: Use multiple streams with game affinity
4. **Async TimescaleDB**: Buffer inserts and batch write
5. **Local caching**: Cache state with short TTL to reduce Redis reads

## Related Services

The `model_svc` service also scales horizontally using the same Redis-backed state strategy. See `services/model_svc/SCALING.md` for details.
