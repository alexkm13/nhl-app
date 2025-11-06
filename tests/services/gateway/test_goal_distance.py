"""Tests for goal distance calculation."""
import pytest
import math


def calculate_goal_distance(x_coord: float, y_coord: float, goal_x: float) -> int:
    """
    Calculate distance from shot location to goal using Euclidean distance.
    
    Args:
        x_coord: X coordinate of shot (0-200)
        y_coord: Y coordinate of shot (-42.5 to 42.5)
        goal_x: X coordinate of goal (0 or 200)
    
    Returns:
        Distance in feet, rounded to nearest integer
    """
    return int(round(math.sqrt((x_coord - goal_x)**2 + y_coord**2)))


@pytest.mark.unit
class TestGoalDistance:
    """Test goal distance calculations."""
    
    def test_center_ice_shot(self):
        """Test shot from center ice."""
        # Shot from center ice (x=100, y=0) to goal at x=0
        distance = calculate_goal_distance(100, 0, 0)
        assert distance == 100
        print(f"Center ice shot: {distance} feet")
    
    def test_center_ice_shot_to_other_goal(self):
        """Test shot from center ice to other goal."""
        # Shot from center ice (x=100, y=0) to goal at x=200
        distance = calculate_goal_distance(100, 0, 200)
        assert distance == 100
        print(f"Center ice shot (other goal): {distance} feet")
    
    def test_close_shot_center(self):
        """Test shot very close to goal from center."""
        # Shot from close to goal (x=10, y=0) to goal at x=0
        distance = calculate_goal_distance(10, 0, 0)
        assert distance == 10
        print(f"Close shot center: {distance} feet")
    
    def test_side_shot(self):
        """Test shot from the side of the rink."""
        # Shot from side (x=50, y=20) to goal at x=0
        distance = calculate_goal_distance(50, 20, 0)
        expected = int(round(math.sqrt(50**2 + 20**2)))
        assert distance == expected
        print(f"Side shot (x=50, y=20): {distance} feet")
    
    def test_corner_shot(self):
        """Test shot from corner near goal."""
        # Shot from corner (x=10, y=40) to goal at x=0
        distance = calculate_goal_distance(10, 40, 0)
        expected = int(round(math.sqrt(10**2 + 40**2)))
        assert distance == expected
        print(f"Corner shot (x=10, y=40): {distance} feet")
    
    def test_behind_goal_shot(self):
        """Test shot from behind the goal line."""
        # Shot from behind goal (x=5, y=35) to goal at x=0
        distance = calculate_goal_distance(5, 35, 0)
        expected = int(round(math.sqrt(5**2 + 35**2)))
        assert distance == expected
        print(f"Behind goal shot (x=5, y=35): {distance} feet")
    
    def test_blue_line_shot(self):
        """Test shot from blue line (60 feet from goal)."""
        # Shot from blue line (x=60, y=0) to goal at x=0
        distance = calculate_goal_distance(60, 0, 0)
        assert distance == 60
        print(f"Blue line shot: {distance} feet")
    
    def test_blue_line_side_shot(self):
        """Test shot from blue line but to the side."""
        # Shot from blue line side (x=60, y=25) to goal at x=0
        distance = calculate_goal_distance(60, 25, 0)
        expected = int(round(math.sqrt(60**2 + 25**2)))
        assert distance == expected
        print(f"Blue line side shot (x=60, y=25): {distance} feet")
    
    def test_far_shot_center(self):
        """Test shot from far away, center ice."""
        # Shot from far (x=150, y=0) to goal at x=200
        distance = calculate_goal_distance(150, 0, 200)
        assert distance == 50
        print(f"Far shot center: {distance} feet")
    
    def test_far_shot_side(self):
        """Test shot from far away, to the side."""
        # Shot from far side (x=150, y=30) to goal at x=200
        distance = calculate_goal_distance(150, 30, 200)
        expected = int(round(math.sqrt(50**2 + 30**2)))
        assert distance == expected
        print(f"Far shot side (x=150, y=30): {distance} feet")
    
    def test_negative_x_coordinate(self):
        """Test shot with negative x coordinate (alternative coordinate system)."""
        # Shot from negative x (x=-50, y=20) to goal at x=-89
        distance = calculate_goal_distance(-50, 20, -89)
        expected = int(round(math.sqrt((-50 - (-89))**2 + 20**2)))
        assert distance == expected
        print(f"Negative x shot (x=-50, y=20, goal_x=-89): {distance} feet")
    
    def test_extreme_side_shot(self):
        """Test shot from extreme side of rink."""
        # Shot from extreme side (x=30, y=42) to goal at x=0
        distance = calculate_goal_distance(30, 42, 0)
        expected = int(round(math.sqrt(30**2 + 42**2)))
        assert distance == expected
        print(f"Extreme side shot (x=30, y=42): {distance} feet")


@pytest.mark.integration
class TestGoalDistanceScenarios:
    """Test realistic game scenarios."""
    
    def test_scenario_1_close_wrist_shot(self):
        """Scenario: Close wrist shot from slot."""
        x_coord = 15
        y_coord = 5
        goal_x = 0
        distance = calculate_goal_distance(x_coord, y_coord, goal_x)
        print("\nScenario 1 - Close wrist shot from slot:")
        print(f"  Location: x={x_coord}, y={y_coord}")
        print(f"  Goal: x={goal_x}")
        print(f"  Distance: {distance} feet")
        assert 15 <= distance <= 17
    
    def test_scenario_2_slap_shot_from_point(self):
        """Scenario: Slap shot from point."""
        x_coord = 60
        y_coord = 0
        goal_x = 0
        distance = calculate_goal_distance(x_coord, y_coord, goal_x)
        print("\nScenario 2 - Slap shot from point:")
        print(f"  Location: x={x_coord}, y={y_coord}")
        print(f"  Goal: x={goal_x}")
        print(f"  Distance: {distance} feet")
        assert distance == 60
    
    def test_scenario_3_wrap_around(self):
        """Scenario: Wrap-around attempt."""
        x_coord = 0  # At goal line
        y_coord = 3  # Slightly to side (wrapping around post)
        goal_x = 0
        distance = calculate_goal_distance(x_coord, y_coord, goal_x)
        print("\nScenario 3 - Wrap-around attempt:")
        print(f"  Location: x={x_coord}, y={y_coord}")
        print(f"  Goal: x={goal_x}")
        print(f"  Distance: {distance} feet")
        assert 3 <= distance <= 4  # Very close to goal
    
    def test_scenario_3b_wrap_around_corner(self):
        """Scenario: Wrap-around from corner."""
        x_coord = -2  # Behind goal line
        y_coord = 12  # Wrapping around post from corner
        goal_x = 0
        distance = calculate_goal_distance(x_coord, y_coord, goal_x)
        print("\nScenario 3b - Wrap-around from corner:")
        print(f"  Location: x={x_coord}, y={y_coord}")
        print(f"  Goal: x={goal_x}")
        print(f"  Distance: {distance} feet")
        assert 12 <= distance <= 13  # Close but wrapping around post
    
    def test_scenario_4_one_timer_from_circle(self):
        """Scenario: One-timer from faceoff circle."""
        x_coord = 25
        y_coord = 20
        goal_x = 0
        distance = calculate_goal_distance(x_coord, y_coord, goal_x)
        print("\nScenario 4 - One-timer from faceoff circle:")
        print(f"  Location: x={x_coord}, y={y_coord}")
        print(f"  Goal: x={goal_x}")
        print(f"  Distance: {distance} feet")
        assert 31 <= distance <= 33
    
    def test_scenario_5_long_range_shot(self):
        """Scenario: Long range shot from center ice."""
        x_coord = 100
        y_coord = 0
        goal_x = 0
        distance = calculate_goal_distance(x_coord, y_coord, goal_x)
        print("\nScenario 5 - Long range shot from center ice:")
        print(f"  Location: x={x_coord}, y={y_coord}")
        print(f"  Goal: x={goal_x}")
        print(f"  Distance: {distance} feet")
        assert distance == 100


def test_distance_comparison():
    """Compare Euclidean vs horizontal distance to show why Euclidean is needed."""
    print("\n" + "="*60)
    print("DISTANCE COMPARISON: Euclidean vs Horizontal Only")
    print("="*60)
    
    test_cases = [
        ("Center ice shot", 50, 0, 0),
        ("Side shot", 50, 20, 0),
        ("Corner shot", 10, 40, 0),
        ("Behind goal", 5, 35, 0),
        ("Blue line side", 60, 25, 0),
    ]
    
    for name, x, y, goal_x in test_cases:
        euclidean = calculate_goal_distance(x, y, goal_x)
        horizontal = abs(goal_x - x)
        difference = euclidean - horizontal
        pct_error = (difference / euclidean * 100) if euclidean > 0 else 0
        
        print(f"\n{name}:")
        print(f"  Location: x={x}, y={y}")
        print(f"  Goal: x={goal_x}")
        print(f"  Euclidean distance: {euclidean} feet")
        print(f"  Horizontal only: {horizontal} feet")
        print(f"  Difference: {difference} feet ({pct_error:.1f}% error)")
    
    print("\n" + "="*60)

