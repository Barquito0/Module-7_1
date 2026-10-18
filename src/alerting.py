"""Persistent alert with 3-sample activation + hysteresis and 2-sample clearing."""
from dataclasses import dataclass

@dataclass
class AlertEngine:
    active: bool = False
    high_count: int = 0
    clear_count: int = 0
    trigger: float = 30.0
    clear: float = 28.5
    required_high: int = 3
    required_clear: int = 2

    def update(self, value, accepted=True):
        """Return: NONE, ACTIVATED, CLEARED. Rejected samples reset streaks."""
        if not accepted or value is None:
            self.high_count = 0
            self.clear_count = 0
            return 'NONE'
        if not self.active:
            self.high_count = self.high_count + 1 if value >= self.trigger else 0
            if self.high_count >= self.required_high:
                self.active = True
                self.high_count = 0
                return 'ACTIVATED'
        else:
            self.clear_count = self.clear_count + 1 if value <= self.clear else 0
            if self.clear_count >= self.required_clear:
                self.active = False
                self.clear_count = 0
                return 'CLEARED'
        return 'NONE'

    def serialize(self):
        return {'active':self.active,'high_count':self.high_count,'clear_count':self.clear_count}

    @classmethod
    def from_state(cls, state):
        s = state or {}
        return cls(active=s.get('active',False),high_count=s.get('high_count',0),
                   clear_count=s.get('clear_count',0))
