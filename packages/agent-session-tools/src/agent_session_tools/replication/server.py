"""SSH forced-command entrypoint. No peer, path or config is accepted from packets."""

import argparse
import sys

from .endpoint import Endpoint
from .policy import ReplicaError
from .ssh import require_forced_command
from .wire import serve


def run(peer):
    require_forced_command()
    endpoint = Endpoint(peer)
    serve(endpoint, sys.stdin.fileno(), sys.stdout.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", required=True)
    args = parser.parse_args()
    try:
        run(args.peer)
    except (ReplicaError, OSError, ValueError):
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
