#!/usr/bin/env python3
"""Smoke test for tool permission and confirmation."""
import sys
import os
import time

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from tools.registry import TOOLS, run_tool, ToolExecutionContext, _has_required_role
from tools.confirmation import get_confirmation_store


def test_tool_risk_levels():
    """Test that all tools have risk levels defined."""
    print("Testing tool risk levels...")
    for tool_name, spec in TOOLS.items():
        assert spec.risk_level in {"low", "medium", "high", "destructive"}, f"{tool_name} has invalid risk_level: {spec.risk_level}"
        assert spec.side_effect in {"read", "write", "external_call", "session_create", None}, f"{tool_name} has invalid side_effect: {spec.side_effect}"
        assert spec.required_role in {"anonymous", "student", "teacher", "admin", None}, f"{tool_name} has invalid required_role: {spec.required_role}"
    print(f"✓ All {len(TOOLS)} tools have valid risk levels")
    return True


def test_role_check():
    """Test role checking logic."""
    print("Testing role check...")
    # Anonymous context
    anon_context = ToolExecutionContext(role="anonymous", actor_id="anon")
    student_context = ToolExecutionContext(role="student", actor_id="student")
    teacher_context = ToolExecutionContext(role="teacher", actor_id="teacher")

    # Test student-only tool
    spec = TOOLS["start_timeline_game"]
    assert not _has_required_role(anon_context, spec), "Anonymous should not have student role"
    assert _has_required_role(student_context, spec), "Student should have student role"
    assert _has_required_role(teacher_context, spec), "Teacher should have student role"

    print("✓ Role check logic OK")
    return True


def test_confirmation_token():
    """Test confirmation token creation and validation."""
    print("Testing confirmation token...")
    store = get_confirmation_store()

    # Create token
    token = store.create_token("delete_demo_memory", "student_123")
    assert token.startswith("confirm_"), "Token should start with 'confirm_'"

    # Validate valid token
    assert store.validate_token(token, "delete_demo_memory", "student_123"), "Valid token should validate"
    assert not store.validate_token(token, "delete_demo_memory", "student_456"), "Wrong actor should fail"
    assert not store.validate_token(token, "other_tool", "student_123"), "Wrong tool should fail"

    # Consume token
    assert store.consume_token(token), "Token should be consumable"
    assert not store.consume_token(token), "Token should not be consumable twice"
    assert not store.validate_token(token, "delete_demo_memory", "student_123"), "Consumed token should not validate"

    print("✓ Confirmation token OK")
    return True


def test_high_risk_tool_requires_confirmation():
    """Test that high-risk tools require confirmation."""
    print("Testing high-risk tool confirmation requirement...")
    spec = TOOLS["delete_demo_memory"]
    assert spec.risk_level == "high", "delete_demo_memory should be high risk"
    assert spec.requires_confirmation == True, "delete_demo_memory should require confirmation"

    # Test without confirmation
    context = ToolExecutionContext(role="student", actor_id="student_123", confirmed=False)
    result = run_tool("delete_demo_memory", {"student_id": "student_123", "memory_id": "demo_001"}, context)
    assert not result.ok, "Tool should fail without confirmation"
    assert result.error and result.error.code == "confirmation_required", f"Expected confirmation_required, got {result.error.code if result.error else None}"

    print("✓ High-risk tool requires confirmation OK")
    return True


def test_role_denied():
    """Test that tools deny unauthorized roles."""
    print("Testing role denial...")
    # Student-only tool with anonymous context
    context = ToolExecutionContext(role="anonymous", actor_id="anon")
    result = run_tool("start_timeline_game", {"grade": "7", "difficulty": "easy"}, context)
    assert not result.ok, "Tool should fail for anonymous user"
    assert result.error and result.error.code == "role_denied", f"Expected role_denied, got {result.error.code if result.error else None}"

    print("✓ Role denial OK")
    return True


def test_low_risk_tool_no_confirmation():
    """Test that low-risk tools don't require confirmation."""
    print("Testing low-risk tool no confirmation...")
    spec = TOOLS["search_history_knowledge"]
    assert spec.risk_level == "low", "search_history_knowledge should be low risk"
    assert spec.requires_confirmation == False, "search_history_knowledge should not require confirmation"

    print("✓ Low-risk tool no confirmation OK")
    return True


def main():
    """Run all tool permission smoke tests."""
    print("=" * 50)
    print("Tool Permission / Confirmation Smoke Tests")
    print("=" * 50)

    tests = [
        test_tool_risk_levels,
        test_role_check,
        test_confirmation_token,
        test_high_risk_tool_requires_confirmation,
        test_role_denied,
        test_low_risk_tool_no_confirmation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ {test.__name__} FAILED: {e}")

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
