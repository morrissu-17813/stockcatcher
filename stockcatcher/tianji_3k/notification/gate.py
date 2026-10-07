from dataclasses import dataclass

MOMENTUM_UP_PCT = 9.5

@dataclass(frozen=True)
class NotificationDecision:
    should_send: bool
    status: str
    suppression_reason: str | None = None
    def to_dict(self):
        return {
            "should_send": self.should_send,
            "status": self.status,
            "suppression_reason": self.suppression_reason,
        }

def evaluate_intraday_notification(up_pct):
    # High-momentum signals are no longer suppressed. They are labeled
    # MOMENTUM downstream so the user can distinguish them from normal signals.
    if float(up_pct) >= MOMENTUM_UP_PCT:
        return NotificationDecision(True, "MOMENTUM")
    return NotificationDecision(True, "READY")
