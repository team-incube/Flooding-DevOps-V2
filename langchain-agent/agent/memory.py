"""memory.py — Per-channel conversation memory management."""
from langchain.memory import ConversationBufferWindowMemory

_memory_store: dict[str, ConversationBufferWindowMemory] = {}


def get_memory(channel_id: str) -> ConversationBufferWindowMemory:
    """Return (or create) a ConversationBufferWindowMemory for a Slack channel."""
    if channel_id not in _memory_store:
        _memory_store[channel_id] = ConversationBufferWindowMemory(
            k=10,
            memory_key="chat_history",
            return_messages=True,
        )
    return _memory_store[channel_id]


def clear_memory(channel_id: str) -> None:
    """Clear conversation memory for a channel."""
    if channel_id in _memory_store:
        _memory_store[channel_id].clear()
