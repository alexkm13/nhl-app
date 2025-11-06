# Interview Guide: NHL Win Probability Prediction System

## Table of Contents
1. [Project Overview](#project-overview)
2. [Technical Deep Dives](#technical-deep-dives)
3. [Common Interview Questions & Answers](#common-interview-questions--answers)
4. [Challenge & Solution Stories](#challenge--solution-stories)
5. [Metrics & Performance](#metrics--performance)
6. [System Design Questions](#system-design-questions)

---

## Project Overview

### What is this project?
A production-ready, real-time NHL win probability prediction system that processes live game events through a microservices pipeline and computes win probabilities using machine learning models.

### Key Components
- **ML Models**: Gradient boosting (LightGBM/XGBoost/CatBoost) trained on historical game data
- **Real-Time Inference**: Event-driven architecture processing live game events
- **Feature Engineering**: 50+ features including score-time interactions, power play dynamics
- **Production Pipeline**: Model training, versioning, A/B testing, and deployment
- **Live Visualization**: Dynamic probability graphs updated in real-time

---

## Technical Deep Dives

### Machine Learning Model

**Question: "Tell me about your ML model"**

**Answer:**
"I trained gradient boosting models—specifically LightGBM, XGBoost, and CatBoost—to predict win probability in NHL games. The model takes game state features as input and outputs a probability between 0 and 1.

**Key aspects:**
- **Model Selection**: I chose gradient boosting because:
  - It handles non-linear relationships well (score-time interactions)
  - Provides good feature importance insights
  - Fast inference suitable for real-time predictions (<10ms)
  - Robust to outliers in game data

- **Feature Engineering**: I created 50+ features including:
  - **Score features**: Score differential, score ratio, leading indicators
  - **Time features**: Seconds elapsed, time remaining, period, time normalized
  - **Critical interactions**: Score-time interactions (score matters more late in game)
  - **Power play features**: Strength situation (EV, PP, PK), power play advantages
  - **Game state**: Recent events, empty net situations

- **Training Process**:
  - Trained on historical NHL game data (2023-2024 season, ~50,000+ game state snapshots)
  - Used train/test split with temporal validation (training on past, testing on future)
  - Implemented model calibration using Platt scaling for probability reliability
  - Clipped probabilities to 0.05-0.95 to prevent overconfidence

- **Model Evaluation**:
  - Log loss for probability calibration (target: <0.5)
  - Brier score for prediction accuracy (target: <0.2)
  - Binary classification accuracy (target: >70%)
  - Feature importance analysis to understand model behavior
  - Validated on held-out test set

**Question: "Why did you choose gradient boosting over other models?"**

**Answer:**
"I evaluated several approaches and chose gradient boosting for several reasons:

1. **Non-linear relationships**: NHL games have complex interactions (e.g., a 1-goal lead with 10 minutes left vs. 1 minute left has very different implications). Gradient boosting captures these interactions through tree ensembles.

2. **Feature importance**: The model provides interpretable feature importance, which helped me validate that the features made sense (e.g., score differential is most important, time remaining is critical).

3. **Inference speed**: Gradient boosting models are fast at inference time (<10ms per prediction), which is crucial for real-time predictions.

4. **Robustness**: Gradient boosting handles outliers well—games can have unusual scores or events, and the model generalizes well.

I also considered:
- **Neural networks**: Could work but harder to interpret, slower inference, overkill for this problem size
- **Logistic regression**: Too simple, can't capture complex interactions effectively
- **Random forest**: Good but gradient boosting generally performs better for this type of problem"

---

### Feature Engineering

**Question: "Tell me about your feature engineering process"**

**Answer:**
"I engineered 50+ features organized into several categories:

**1. Basic Score Features:**
- Score differential (home_score - away_score)
- Absolute score differential
- Total goals scored
- Score ratio (handling division by zero)

**2. Time Features:**
- Seconds elapsed from game start
- Time remaining in game
- Period number (1-7 for regulation + OT)
- Time normalized (0-1, where 1 = end of regulation)

**3. Critical Score-Time Interactions:**
This was the most important part. A 1-goal lead means different things at different times:
- `score_diff_time_interaction`: Score differential weighted by time remaining
- `score_diff_urgency`: Score diff per minute remaining (higher when time is low)
- `late_game_score_impact`: Amplifies score_diff when late in game
- `early_game_dampening`: Reduces impact of early game leads (prevents over-weighting early goals)

**4. Power Play Features:**
- Binary indicators for strength situations (EV, PP, PK)
- Power play advantages (home_pp, away_pp)
- Power play interactions:
  - `home_pp_with_lead`: Power play when already leading
  - `home_pp_late_game`: Power play late in game (more critical)
  - `home_pp_score_boost`: Power play + score differential interaction

**5. Game State Features:**
- Last event type (GOAL, SHOT, PENALTY, etc.)
- Empty net indicators
- Regulation vs. overtime vs. shootout

**Why these features matter:**
- The score-time interactions are critical because the model needs to understand that a 1-goal lead with 1 minute left is much more valuable than a 1-goal lead with 10 minutes left
- Power play features capture situational advantages that significantly impact win probability
- The interactions help the model understand context, not just raw numbers

**Feature engineering consistency:**
- Shared `feature_engineer.py` module used by both training and inference
- Comprehensive tests to ensure feature engineering matches
- Versioned feature engineering code with model versions"

---

### System Architecture

**Question: "Walk me through your system architecture"**

**Answer:**
"I designed an event-driven microservices architecture using Redis Streams:

**1. Ingestor Service:**
- Fetches live game events from NHL API
- Publishes events to Redis Streams (`events` stream)
- Handles game state changes, new periods, etc.

**2. Feature State Service:**
- Consumes events from `events` stream
- Maintains current game state (score, time, strength, etc.)
- Engineers features from game state
- Publishes feature vectors to `features` stream

**3. Model Service:**
- Consumes feature vectors from `features` stream
- Runs ML model inference (<10ms per prediction)
- Applies calibration and probability clipping
- Publishes predictions to `predictions` stream
- Stores latest prediction in Redis hash for quick access

**4. Gateway Service:**
- REST API endpoints for win probability queries
- WebSocket streaming for real-time updates
- Serves frontend with live probability graphs
- Caches predictions for performance

**Data flow:**
```
NHL API → Ingestor → Redis Streams (events) → Feature State → 
Redis Streams (features) → Model Service → Redis Streams (predictions) → 
Gateway → API/WebSocket → Frontend
```

**Why this architecture:**
- **Scalability**: Each service can scale independently (e.g., multiple model service instances for load)
- **Fault tolerance**: If one service fails, others continue working
- **Real-time**: Event-driven design ensures low latency (<50ms end-to-end)
- **Observability**: Each service exposes Prometheus metrics

**Technology choices:**
- **Redis Streams**: Chose over Kafka for simplicity initially, but designed to be swappable
- **FastAPI**: High-performance async Python framework
- **Docker Compose**: Easy local development and deployment
- **Prometheus + Grafana**: Monitoring and observability"

---

### Real-Time Processing

**Question: "How do you ensure real-time predictions?"**

**Answer:**
"Real-time processing was critical. Here's how I achieved it:

**1. Event-Driven Architecture:**
- Events flow through streams without blocking
- Each service processes events asynchronously
- No polling—everything is push-based

**2. Low-Latency Inference:**
- Model inference is <10ms per prediction
- Feature engineering is deterministic and fast (<5ms)
- Total pipeline latency: ~50ms from event to prediction

**3. Caching Strategy:**
- Latest predictions cached in Redis hash for instant REST API responses
- Frontend caches game data to reduce API calls
- WebSocket provides live updates without polling

**4. Consumer Groups:**
- Each service uses Redis consumer groups
- Multiple instances can process in parallel
- Automatically handles back-pressure and load balancing

**5. Optimization:**
- Pre-loaded models in memory (no disk I/O during inference)
- Efficient feature engineering (no unnecessary calculations)
- Async processing (no blocking operations)

**Monitoring:**
- Prometheus metrics track:
  - Prediction latency (p50, p95, p99)
  - Events processed per second
  - Model inference time
  - Cache hit rates

**Challenges solved:**
- Initially had race conditions with multiple services updating state
- Fixed with atomic Redis operations and proper event ordering
- Had to handle late-arriving events (game ends but events still in queue)
- Implemented final event processing after game state changes"

---

### Model Training & Evaluation

**Question: "How did you train and evaluate your model?"**

**Answer:**
"I built a comprehensive training pipeline:

**1. Data Collection:**
- Collected historical NHL game data from 2020-2025 seasons
- Processed play-by-play data to extract game states
- Created snapshots at each event (goal, shot, penalty, etc.)
- Total dataset: ~50,000+ game state snapshots

**2. Training Process:**
- **Temporal validation**: Split data chronologically (train on past, test on future)
- **Hyperparameter tuning**: Used grid search for learning rate, max depth, n_estimators
- **Early stopping**: Prevented overfitting with validation set
- **Feature selection**: Used feature importance to identify critical features

**3. Model Evaluation:**
- **Primary metrics**:
  - Log loss: Measures probability calibration (lower is better, target: <0.5)
  - Brier score: Measures prediction accuracy (lower is better, target: <0.2)
  - Accuracy: Binary classification accuracy (target: >70%)

- **Validation**:
  - Cross-validation on training data
  - Test set performance (held-out data)
  - Real-time validation on live games

**4. Model Calibration:**
- Applied Platt scaling to calibrate probabilities
- Important because uncalibrated models can be overconfident
- Ensures probabilities are meaningful (e.g., 70% prediction should win 70% of the time)

**5. Experiment Tracking:**
- Each training run creates an experiment directory
- Saves: model file, metrics, feature importance, config
- Model registry tracks all trained models
- Easy to compare different model versions

**6. Production Validation:**
- Created integration tests simulating full games
- Validates that model updates correctly with each event
- Tests edge cases (overtime, shootout, late goals)
- Verifies that late-game events are processed correctly"

---

## Common Interview Questions & Answers

### Q: "Why did you choose this project?"

**A:**
"I wanted to build something that combined my interests in sports analytics and machine learning. NHL games are perfect for this because:
- Rich data available (play-by-play, scores, time, events)
- Clear problem (win probability prediction)
- Real-time requirements (live games)
- Visible impact (probability graphs update in real-time)

It also let me practice:
- End-to-end ML engineering (from data to production)
- Real-time systems (event-driven architecture)
- Production ML (monitoring, A/B testing, deployment)
- Full-stack development (backend API + frontend visualization)"

---

### Q: "What would you do differently if you started over?"

**A:**
"Several things:

1. **Start with simpler model**: I'd start with a logistic regression baseline, then iterate to gradient boosting. This helps validate the approach before complexity.

2. **Better data validation**: I'd add more data validation early—checking for missing values, outliers, data quality issues before training.

3. **More comprehensive testing earlier**: I'd write tests alongside code development, not after. This would have caught bugs earlier.

4. **Feature importance analysis earlier**: I'd analyze feature importance during development to understand what matters most, rather than after training.

5. **Production monitoring from day one**: I'd set up monitoring and alerting earlier to catch issues in production faster.

6. **Better documentation**: I'd document design decisions and trade-offs as I made them, not after the fact.

However, I'm happy with the architecture choices—the microservices design and event-driven approach worked well."

---

### Q: "How do you handle model drift?"

**A:**
"Model drift is a real concern in production ML. Here's my approach:

1. **Monitoring**: Track prediction accuracy over time. If accuracy degrades, it's a sign of drift.

2. **Data validation**: Monitor input data distributions. If game patterns change (e.g., more overtime games), the model might need retraining.

3. **Regular retraining**: Retrain models periodically (e.g., monthly) with recent data to adapt to changing patterns.

4. **A/B testing**: Use A/B testing to compare new models against current models before full rollout.

5. **Feature monitoring**: Track feature distributions to detect when features change significantly.

6. **Alerting**: Set up alerts for significant changes in prediction distributions or accuracy metrics.

7. **Version control**: Keep model versions and can roll back if new model performs worse.

**Future improvements**:
- Implement automated retraining pipeline
- Add concept drift detection
- Implement online learning (though gradient boosting is batch-based)
- Add more sophisticated monitoring for data drift"

---

### Q: "How would you scale this to handle all NHL games simultaneously?"

**A:**
"Currently handles one game, but scaling to all games is straightforward:

1. **Horizontal scaling**: Each service can have multiple instances. With 32 teams playing ~1300 games/year, we'd need:
   - Multiple ingestors (one per game or shared)
   - Multiple feature state services (process multiple games)
   - Multiple model services (parallel inference)
   - Multiple gateway instances (load balancing)

2. **Resource optimization**:
   - Model services can share model in memory (one model instance per worker)
   - Redis can handle multiple streams (one per game or shared streams)
   - Database can partition by game_id

3. **Architecture changes**:
   - Use game_id as partition key
   - Each game gets its own stream or shared streams with routing
   - Load balancer routes requests by game_id
   - Caching strategy per game

4. **Monitoring**:
   - Per-game metrics (latency per game)
   - Aggregate metrics (total games processed)
   - Alerting on per-game failures

5. **Database scaling**:
   - TimescaleDB can handle time-series data for all games
   - Partition by game_id and time
   - Efficient queries with proper indexing

**Estimated capacity**:
- Current: ~1 game, ~50ms latency
- Scaled: ~1000+ games, ~100ms latency (with proper infrastructure)
- Bottleneck: Likely API rate limits (NHL API), not our system"

---

### Q: "What metrics do you track?"

**A:**
"Comprehensive metrics:

**Model Performance:**
- Prediction accuracy (log loss, Brier score)
- Probability calibration (do 70% predictions win 70% of the time?)
- Feature importance rankings
- Prediction distribution (are we overconfident?)

**System Performance:**
- Prediction latency (p50, p95, p99)
- Events processed per second
- Model inference time
- API response time
- Cache hit rate

**Business Metrics:**
- Predictions made per game
- API requests per game
- WebSocket connections
- User engagement (if applicable)

**Reliability:**
- Error rate
- Service uptime
- Failed predictions
- Cache misses

**Monitoring**:
- Prometheus for metrics collection
- Grafana for visualization
- Alerting on anomalies
- Logs for debugging

**Key metrics to watch**:
- If prediction latency > 100ms: investigate
- If error rate > 1%: investigate
- If cache hit rate < 80%: investigate
- If model accuracy drops: retrain model"

---

### Q: "How do you ensure model accuracy in production?"

**A:**
"Multiple strategies:

1. **Validation**: Test set performance validated before deployment
2. **A/B testing**: Compare new models against current models
3. **Real-time validation**: Track prediction accuracy on live games
4. **Probability calibration**: Ensure probabilities are meaningful
5. **Feature validation**: Ensure features match training distribution
6. **Monitoring**: Track accuracy metrics over time
7. **Integration tests**: Test full game scenarios to ensure correctness

**Example validation**:
- If model predicts 70% win probability for home team
- Over many games with 70% predictions, home team should win ~70% of the time
- If not, model needs calibration or retraining

**Continuous improvement**:
- Collect production data
- Retrain periodically with recent data
- Compare new models before deploying
- Roll back if performance degrades"

---

## Challenge & Solution Stories

### Challenge 1: Ensuring Late-Game Events Are Processed

**Problem**: When a game ends, the game state changes to 'FINAL', but there might still be events in the queue that haven't been processed. The initial code would stop polling when the game state changed, missing final events.

**Solution**: 
- Implemented a `game_ended` flag that allows one final iteration after the game state changes
- The polling loop continues until all events are processed, even after the game ends
- This ensures the model sees all events, including late goals that might affect the final prediction

**Code solution**:
```python
game_ended = False
while True:
    if game_state not in ["LIVE", "CRIT"]:
        if not game_ended:
            game_ended = True
            logger.info(f"Game {game_id} has ended, processing final events before stopping")
        else:
            logger.info(f"Game {game_id} is no longer live, stopping polling after processing final events")
            break
    # Process events...
    if game_ended and no_new_events:
        break
```

**Impact**: This was critical because late-game events (like a goal in the final seconds) can significantly change win probability, and missing them would make the model inaccurate.

---

### Challenge 2: Race Conditions in Frontend Updates

**Problem**: The frontend was refreshing too frequently and would reset to the 'Feed' tab whenever new data arrived, even if the user was viewing a different tab.

**Solution**:
- Added tab state preservation before re-rendering
- Only update specific sections (graph) without full page refresh
- Implemented smart caching to prevent unnecessary updates
- Added debouncing for rapid updates

**Impact**: Users can now view different tabs (Game, Team1, Team2) without being interrupted by updates.

---

### Challenge 3: Model Overconfidence

**Problem**: Initial model was overconfident—predicting 90%+ win probability too early in games.

**Solution**:
- Added early game dampening features to reduce impact of early leads
- Implemented probability clipping (0.05-0.95) to prevent extreme predictions
- Applied model calibration using Platt scaling
- Adjusted feature weights based on feature importance analysis

**Impact**: More realistic probabilities throughout the game, better user experience.

---

### Challenge 4: Real-Time Feature Engineering Consistency

**Problem**: Feature engineering had to match exactly between training and inference, or predictions would be wrong.

**Solution**:
- Created a shared `feature_engineer.py` module used by both training and inference
- Comprehensive tests to ensure feature engineering matches
- Versioned feature engineering code with model versions
- Validation checks in production to catch mismatches

**Impact**: Predictions are accurate and consistent between training and production.

---

## Testing Strategy

**Question: "How did you test your ML system?"**

**Answer:**
"I implemented a comprehensive testing strategy:

**1. Unit Tests:**
- Feature engineering tests (each feature calculated correctly)
- Model inference tests (predictions are valid probabilities)
- Distance calculation tests (goal distances are accurate)
- Graph generation tests (probability graphs are correct)

**2. Integration Tests:**
- **Full game simulation**: Tests that simulate a complete game with events
- Validates that model updates correctly with each event
- Tests that predictions change appropriately with score changes
- Verifies that late-game events are processed

**3. API Tests:**
- REST API endpoint tests
- WebSocket streaming tests
- Error handling tests
- Cache behavior tests

**4. End-to-End Tests:**
- Complete pipeline test: event → feature → prediction → API response
- Real-time update tests
- Graph visualization tests

**5. Edge Case Tests:**
- Overtime scenarios
- Shootout scenarios
- Empty net situations
- Late goals
- Game state transitions

**Test coverage**: 
- 17+ tests for graph functionality
- 21+ tests for probability model
- 10+ tests for feed rendering
- Integration tests for full game simulation

**Example test**:
```python
async def test_game_event_pipeline():
    # Simulate full game with events
    # Verify events are published
    # Verify features are generated
    # Verify predictions are created
    # Verify final score matches
```

**Why this matters**:
- Ensures model correctness in production
- Catches bugs before they reach users
- Validates that real-time updates work correctly
- Gives confidence in system reliability"

---

## Production Considerations

**Question: "How did you make this production-ready?"**

**Answer:**
"Several production considerations:

**1. Model Deployment:**
- Model versioning and registry
- A/B testing framework for comparing models
- Gradual rollout capability
- Model rollback if new model performs worse

**2. Monitoring:**
- Prometheus metrics for:
  - Prediction latency (p50, p95, p99)
  - Events processed per second
  - Model inference time
  - Cache hit rates
  - Error rates

- Grafana dashboards for visualization
- Alerting on anomalies (high latency, errors)

**3. Error Handling:**
- Graceful degradation (fallback to simple probability model if ML model fails)
- Retry logic for API calls
- Timeout handling
- Error logging with context

**4. Performance:**
- Caching strategies (Redis for predictions)
- Async processing (no blocking operations)
- Efficient feature engineering
- Pre-loaded models in memory

**5. Scalability:**
- Microservices can scale independently
- Horizontal scaling support (multiple instances)
- Consumer groups for load distribution
- Designed to swap Redis Streams for Kafka if needed

**6. Testing:**
- Comprehensive test suite
- Integration tests for full game scenarios
- Performance tests
- Load tests

**7. Documentation:**
- API documentation
- Architecture documentation
- Runbook for operations
- Code comments and docstrings"

---

## System Design Questions

### Q: "How would you design this for 1 million concurrent users?"

**A:**
"Scaling architecture:

1. **Load Balancing**:
   - Multiple gateway instances behind load balancer
   - Geographic distribution (CDN for static content)
   - Session affinity for WebSocket connections

2. **Caching Strategy**:
   - Multi-layer caching:
     - CDN for static content
     - Redis for predictions (hot data)
     - Application-level caching (in-memory)
   - Cache invalidation strategy per game

3. **Database Scaling**:
   - Read replicas for queries
   - Write sharding by game_id
   - TimescaleDB for time-series (handles scale well)
   - Connection pooling

4. **Streaming Architecture**:
   - Swap Redis Streams for Kafka (better for high throughput)
   - Multiple partitions per game or topic
   - Consumer groups for parallel processing

5. **Model Service**:
   - Model in shared memory (one instance per worker)
   - Batch inference where possible
   - Model caching (pre-loaded in memory)

6. **API Optimization**:
   - Rate limiting per user
   - Request batching
   - GraphQL for flexible queries
   - WebSocket connection pooling

7. **Monitoring**:
   - Distributed tracing (e.g., Jaeger)
   - Aggregated metrics
   - Per-service monitoring
   - Alerting on degradation

**Estimated capacity**:
- 1 million users, 1000 concurrent games
- ~1000 requests/second per game
- ~1 million total requests/second
- Need: ~100 gateway instances, ~50 model service instances, ~20 feature state instances"

---

### Q: "How do you handle data quality issues?"

**A:**
"Multiple layers of data validation:

1. **Input Validation**:
   - Check for missing coordinates
   - Validate coordinate ranges (x: 0-200, y: -42.5 to 42.5)
   - Validate event types
   - Check for impossible game states

2. **Data Cleaning**:
   - Handle missing values (defaults or interpolation)
   - Detect outliers (e.g., impossible coordinates)
   - Validate game state transitions (can't have negative score)

3. **Feature Validation**:
   - Ensure features are in expected ranges
   - Check for NaN or infinite values
   - Validate feature engineering output

4. **Model Validation**:
   - Check predictions are valid probabilities (0-1)
   - Detect anomalous predictions (e.g., 99% when score is tied)
   - Log warnings for unusual patterns

5. **Monitoring**:
   - Track data quality metrics
   - Alert on data anomalies
   - Log data quality issues

**Example**:
```python
# Validate coordinates
if x_coord is None or y_coord is None:
    logger.warning("Missing coordinates")
    return None

if not (0 <= x_coord <= 200) or not (-42.5 <= y_coord <= 42.5):
    logger.warning(f"Invalid coordinates: x={x_coord}, y={y_coord}")
    return None
```"

---

## Metrics & Performance

### Key Metrics to Mention

**Model Performance:**
- Log loss: <0.5 (probability calibration)
- Brier score: <0.2 (prediction accuracy)
- Accuracy: >70% (binary classification)

**System Performance:**
- Prediction latency: <50ms (p50), <100ms (p95)
- Model inference: <10ms per prediction
- Events processed: ~1000 events/second per service
- API response time: <50ms (cached), <200ms (uncached)

**Scalability:**
- Handles 1 game with <50ms latency
- Can scale to 1000+ games with proper infrastructure
- Horizontal scaling support (multiple instances)

---

## Closing Tips

### When to mention specific technologies:
- **LightGBM/XGBoost**: When discussing model choice or performance
- **Redis Streams**: When discussing real-time architecture
- **FastAPI**: When discussing API performance
- **Prometheus**: When discussing observability
- **Docker**: When discussing deployment

### When to mention specific numbers:
- **50+ features**: Shows complexity of feature engineering
- **<50ms latency**: Shows real-time performance
- **17+ tests**: Shows thoroughness
- **50,000+ training samples**: Shows data scale

### When to mention challenges:
- Shows problem-solving skills
- Demonstrates understanding of production ML
- Highlights real-world experience

### When to mention future improvements:
- Shows continuous improvement mindset
- Demonstrates understanding of production ML challenges
- Shows you think beyond the current implementation

---

## Example Interview Flow

**Interviewer**: "Tell me about a project you're proud of."

**You**: "I built an end-to-end real-time NHL win probability prediction system using machine learning. Let me walk you through it..."

[Use Project Overview section]

**Interviewer**: "That's interesting. How does the ML model work?"

**You**: [Use ML Model section]

**Interviewer**: "What was the biggest challenge?"

**You**: [Use Challenge & Solution Stories section]

**Interviewer**: "How would you scale this?"

**You**: [Use System Design Questions section]

---

## Key Takeaways to Emphasize

1. **End-to-end ML engineering**: From data to production
2. **Real-time systems**: Event-driven architecture
3. **Production ML**: Monitoring, A/B testing, deployment
4. **Problem-solving**: Challenges faced and solutions
5. **Testing**: Comprehensive test coverage
6. **Performance**: Low latency, high throughput
7. **Scalability**: Designed for horizontal scaling

---

## Additional Talking Points

### Code Quality & Best Practices
- Comprehensive test coverage (unit, integration, end-to-end)
- Code organization and modularity
- Error handling and logging
- Documentation and comments
- Version control and model versioning

### Production ML Skills
- Model deployment and serving
- A/B testing framework
- Monitoring and observability
- Model calibration
- Feature engineering consistency
- Model versioning and rollback

### System Design Skills
- Microservices architecture
- Event-driven design
- Scalability considerations
- Fault tolerance
- Performance optimization
- Caching strategies

### Problem-Solving Skills
- Identified and fixed late-game event processing bug
- Resolved frontend race conditions
- Addressed model overconfidence
- Ensured feature engineering consistency

---

Good luck with your interviews! 🚀

