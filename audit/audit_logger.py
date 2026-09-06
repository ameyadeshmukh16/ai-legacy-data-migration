import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

class AuditLogger:
    """Append-only hash-chained JSON audit logger."""
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=Lock()
        if not self.path.exists(): self.path.write_text("[]",encoding="utf-8")
    def append(self,run_id,event_type,payload):
        with self.lock:
            events=json.loads(self.path.read_text(encoding="utf-8"))
            prev=events[-1]["hash"] if events else "GENESIS"
            event={"event_id":str(uuid4()),"run_id":run_id,
                   "timestamp":datetime.now(timezone.utc).isoformat(),
                   "event_type":event_type,"payload":payload,"previous_hash":prev}
            canonical=json.dumps(event,sort_keys=True,separators=(",",":"))
            event["hash"]=hashlib.sha256((prev+canonical).encode()).hexdigest()
            events.append(event)
            self.path.write_text(json.dumps(events,indent=2),encoding="utf-8")
            return event
