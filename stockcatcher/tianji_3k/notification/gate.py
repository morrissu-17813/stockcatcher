from dataclasses import dataclass
MAX_NOTIFY_UP_PCT=9.5
@dataclass(frozen=True)
class NotificationDecision:
    should_send:bool; status:str; suppression_reason:str|None=None
    def to_dict(self): return {'should_send':self.should_send,'status':self.status,'suppression_reason':self.suppression_reason}
def evaluate_intraday_notification(up_pct):
    return NotificationDecision(False,'SUPPRESSED','UP_PCT_GE_9_5') if float(up_pct)>=MAX_NOTIFY_UP_PCT else NotificationDecision(True,'READY')
