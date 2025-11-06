"""Unit tests for gateway utility functions."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

from services.gateway.utils import safe_parse_time, format_period_label


@pytest.mark.unit
class TestUtils:
    """Test utility functions."""
    
    def test_safe_parse_time_valid(self):
        """Test parsing valid time strings."""
        assert safe_parse_time("10:30") == (10, 30)
        assert safe_parse_time("0:00") == (0, 0)
        assert safe_parse_time("19:59") == (19, 59)
    
    def test_safe_parse_time_invalid(self):
        """Test parsing invalid time strings."""
        assert safe_parse_time("invalid") == (0, 0)
        assert safe_parse_time("") == (0, 0)
        assert safe_parse_time("10") == (0, 0)
        assert safe_parse_time(None) == (0, 0)
    
    def test_format_period_label(self):
        """Test period label formatting."""
        assert format_period_label(1) == "1st"
        assert format_period_label(2) == "2nd"
        assert format_period_label(3) == "3rd"
        assert format_period_label(4) == "OT"
        assert format_period_label(5) == "5th"
        assert format_period_label(6) == "6th"
