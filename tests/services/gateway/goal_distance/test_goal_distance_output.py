#!/usr/bin/env python3
"""Test goal distance calculation and show outputs."""
import math


def calculate_goal_distance(x_coord: float, y_coord: float, goal_x: float) -> int:
    """Calculate distance from shot location to goal using Euclidean distance."""
    return int(round(math.sqrt((x_coord - goal_x)**2 + y_coord**2)))


print('='*70)
print('GOAL DISTANCE CALCULATION TEST RESULTS')
print('='*70)
print()

# Basic distance tests
print('Basic Distance Tests:')
print('-'*70)
test_cases = [
    ('Center ice shot', 100, 0, 0),
    ('Close shot center', 10, 0, 0),
    ('Side shot', 50, 20, 0),
    ('Corner shot', 10, 40, 0),
    ('Behind goal shot', 5, 35, 0),
    ('Blue line shot', 60, 0, 0),
    ('Blue line side', 60, 25, 0),
    ('Far shot center', 150, 0, 200),
    ('Far shot side', 150, 30, 200),
    ('Extreme side', 30, 42, 0),
]

for name, x, y, goal_x in test_cases:
    distance = calculate_goal_distance(x, y, goal_x)
    horizontal = abs(goal_x - x)
    diff = distance - horizontal
    pct = (diff / distance * 100) if distance > 0 else 0
    print(f'{name:20s}: x={x:3d}, y={y:4.1f}, goal_x={goal_x:3d} -> {distance:3d} feet (horizontal: {horizontal:3d}, diff: {diff:+3d} feet, {pct:5.1f}% error)')

print()
print('Realistic Game Scenarios:')
print('-'*70)
scenarios = [
    ('Close wrist shot from slot', 15, 5, 0),
    ('Slap shot from point', 60, 0, 0),
    ('Wrap-around attempt', 0, 3, 0),  # At goal line, slightly to side
    ('Wrap-around from corner', -2, 12, 0),  # Behind net, wrapping around post
    ('One-timer from faceoff circle', 25, 20, 0),
    ('Long range shot from center', 100, 0, 0),
]

for name, x, y, goal_x in scenarios:
    distance = calculate_goal_distance(x, y, goal_x)
    print(f'{name:30s}: x={x:3d}, y={y:4.1f} -> {distance:3d} feet')

print()
print('='*70)
print('CONCLUSION: Euclidean distance is needed for accurate shot distance')
print('Horizontal-only distance can be very inaccurate for side shots')
print('='*70)

