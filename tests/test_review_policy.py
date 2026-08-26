import json

from agents.review_policy import assess_review_need
from agents.validation_store import ValidationStore


def test_non_image_agents_do_not_require_image_review():
    decision = assess_review_need(
        agent_name="RAG_AGENT",
        confidence=None,
        confidence_threshold=0.85,
        anomaly_type=None,
        high_risk_anomalies=("tumor",),
        image_quality=None,
    )
    assert decision.required is False
    assert decision.reasons == ()


def test_image_review_reports_quality_confidence_and_anomaly_reasons():
    decision = assess_review_need(
        agent_name="CHEST_XRAY_AGENT",
        confidence=0.42,
        confidence_threshold=0.85,
        anomaly_type="covid19",
        high_risk_anomalies=("covid19", "tumor"),
        image_quality="poor",
    )
    assert decision.required is True
    assert set(decision.reasons) == {
        "low_confidence",
        "low_quality_image",
        "high_risk_anomaly",
    }


def test_validation_audit_records_reason_codes_and_reviewer_identity(monkeypatch):
    monkeypatch.delenv("CHECKPOINT_DATABASE_URL", raising=False)
    store = ValidationStore()
    record = store.create(
        user_id="owner",
        conversation_id="conversation",
        thread_id="thread",
        agent_name="CHEST_XRAY_AGENT",
        original_output="sensitive output",
        review_reasons=("low_confidence",),
    )
    store.resolve(
        record.validation_id,
        user_id="owner",
        conversation_id="conversation",
        result="yes",
        comments="sensitive reviewer note",
        reviewer_id="clinician-7",
    )

    events = store.audit_for_user(record.validation_id, user_id="owner")
    assert [event.event_type for event in events] == ["created", "resolved"]
    assert json.loads(events[0].details_json) == {"review_reasons": ["low_confidence"]}
    assert events[1].actor_id == "clinician-7"
    assert "sensitive output" not in str(events)
    assert "sensitive reviewer note" not in str(events)
