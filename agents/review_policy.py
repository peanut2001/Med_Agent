"""Central, conservative policy for deciding whether medical output needs review."""

from dataclasses import dataclass
from typing import Optional, Sequence


IMAGE_AGENTS = {"BRAIN_TUMOR_AGENT", "CHEST_XRAY_AGENT", "SKIN_LESION_AGENT"}


@dataclass(frozen=True)
class ReviewDecision:
    required: bool
    reasons: tuple[str, ...]


def assess_review_need(
    *,
    agent_name: Optional[str],
    confidence: Optional[float],
    confidence_threshold: float,
    anomaly_type: Optional[str],
    high_risk_anomalies: Sequence[str],
    image_quality: Optional[str],
) -> ReviewDecision:
    """Return structured reason codes; missing safety signals fail to review."""
    if agent_name not in IMAGE_AGENTS:
        return ReviewDecision(False, ())

    reasons = []
    if confidence is None:
        reasons.append("confidence_unavailable")
    elif confidence < confidence_threshold:
        reasons.append("low_confidence")
    if image_quality is None:
        reasons.append("image_quality_unassessed")
    elif image_quality.lower() in {"low", "poor", "invalid", "unknown"}:
        reasons.append("low_quality_image")
    if anomaly_type and anomaly_type.lower() in {item.lower() for item in high_risk_anomalies}:
        reasons.append("high_risk_anomaly")
    if not reasons:
        reasons.append("medical_image_output")
    return ReviewDecision(True, tuple(reasons))
