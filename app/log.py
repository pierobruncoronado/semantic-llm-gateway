import json
import sys
from typing import Any


def log_event(**fields: Any) -> None:
    print(json.dumps(fields, default=str), file=sys.stdout, flush=True)
