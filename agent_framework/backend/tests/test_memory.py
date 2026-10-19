"""ConversationMemory 单元测试：tool 消息链修复与轮次裁剪。"""

from app.agent.memory import ConversationMemory, MessageRole


def _memory(**kwargs) -> ConversationMemory:
    return ConversationMemory(max_tokens=500, preserve_min_messages=4, **kwargs)


def test_repair_removes_orphan_tool_message():
    mem = _memory()
    mem.add_message(MessageRole.USER, "hello")
    mem.add_tool_message("call_1", '{"ok": true}', name="query_sv")

    removed = mem.repair_tool_chain()
    assert removed == 1
    msgs = mem.get_messages()
    assert len(msgs) == 1
    assert msgs[0].role == MessageRole.USER


def test_repair_keeps_complete_tool_round():
    mem = _memory()
    mem.add_message(MessageRole.USER, "查 SV")
    mem.add_assistant_message(
        "",
        tool_calls=[{"id": "call_a", "type": "function", "function": {"name": "query_sv"}}],
    )
    mem.add_tool_message("call_a", '{"results": []}', name="query_sv")

    removed = mem.repair_tool_chain()
    assert removed == 0
    assert len(mem.get_messages()) == 3


def test_pop_oldest_user_turn_keeps_second_turn_intact():
    mem = ConversationMemory(max_tokens=500_000, preserve_min_messages=4)
    mem.add_message(MessageRole.USER, "第一轮")
    mem.add_assistant_message(
        "",
        tool_calls=[{"id": "c1", "type": "function", "function": {"name": "t"}}],
    )
    mem.add_tool_message("c1", '{"ok": true}', name="t")
    mem.add_message(MessageRole.ASSISTANT, "第一轮回答")
    mem.add_message(MessageRole.USER, "第二轮")
    mem.add_message(MessageRole.ASSISTANT, "第二轮回答")

    assert mem._pop_oldest_user_turn() is True
    msgs = mem.get_messages()
    assert msgs[0].content == "第二轮"
    assert not any(m.role == MessageRole.TOOL and m.tool_call_id == "c1" for m in msgs)


def test_rollback_only_dangling_assistant_tool_calls():
    mem = _memory()
    mem.add_message(MessageRole.USER, "q")
    mem.add_assistant_message(
        "",
        tool_calls=[{"id": "c1", "type": "function", "function": {"name": "t"}}],
    )
    mem.add_tool_message("c1", "done", name="t")

    rolled = mem.rollback_incomplete_tool_rounds()
    assert rolled == 0
    assert len(mem.get_messages()) == 3

    mem.add_assistant_message(
        "",
        tool_calls=[{"id": "c2", "type": "function", "function": {"name": "t2"}}],
    )
    rolled = mem.rollback_incomplete_tool_rounds()
    assert rolled == 1
    assert mem.get_messages()[-1].role == MessageRole.TOOL
