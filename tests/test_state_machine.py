"""状态机测试."""

from core.protocol.state_machine import ConnectionStateMachine


def test_state_machine():
    """测试连接状态机."""
    print("=== State Machine Tests ===")

    sm = ConnectionStateMachine()
    assert sm.state == "Stopped"

    sm.on_connected()
    assert sm.state == "Connecting"

    sm.on_startdt_con()
    assert sm.state == "Running"

    sm.on_disconnected()
    assert sm.state == "Stopped"

    print("  ✅ State machine tests passed")
