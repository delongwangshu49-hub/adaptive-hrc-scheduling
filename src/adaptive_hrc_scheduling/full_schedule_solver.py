"""Locked project solver process used by the independent Isaac interpreter."""

import json
import sys

from .contracts.codec import decode
from .domain.production import Configuration
from .full_schedule import mode_proposal

if __name__ == "__main__":
    request = json.load(sys.stdin)
    modes, report = mode_proposal(
        decode(Configuration, request["configuration"]), request["seconds"]
    )
    json.dump(dict(modes=modes, report=report), sys.stdout)
