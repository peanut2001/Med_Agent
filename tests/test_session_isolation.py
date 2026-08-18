from agents.validation_store import ValidationStore


def test_validation_is_scoped_to_user_and_conversation():
    store = ValidationStore()
    record = store.create(
        user_id="user-a",
        conversation_id="conversation-a",
        thread_id="user-a:conversation-a",
        agent_name="CHEST_XRAY_AGENT",
        original_output="result",
    )

    try:
        store.resolve(
            record.validation_id,
            user_id="user-b",
            conversation_id="conversation-a",
            result="yes",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("validation crossed user boundary")

    resolved = store.resolve(
        record.validation_id,
        user_id="user-a",
        conversation_id="conversation-a",
        result="yes",
    )
    assert resolved.status == "approved"
    # A retry is idempotent and cannot change the original decision.
    retry = store.resolve(
        record.validation_id,
        user_id="user-a",
        conversation_id="conversation-a",
        result="no",
    )
    assert retry.status == "approved"

