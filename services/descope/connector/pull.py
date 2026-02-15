#!/usr/bin/env python3
"""Entry-point script for `doubleagent snapshot pull descope`."""

import argparse
import asyncio
import os
import sys

from doubleagent_sdk import ConnectorCredentials, save_snapshot, save_snapshot_incremental
from descope_connector import DescopeConnector


def main():
    parser = argparse.ArgumentParser(description="Pull snapshot from Descope")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--no-redact", action="store_true")
    args = parser.parse_args()

    creds = ConnectorCredentials(
        token=os.environ.get("DESCOPE_MANAGEMENT_KEY"),
        domain=os.environ.get("DESCOPE_PROJECT_ID"),
    )

    connector = DescopeConnector(creds, redact=not args.no_redact)
    if not connector.validate_credentials(creds):
        print("ERROR: Missing DESCOPE_PROJECT_ID or DESCOPE_MANAGEMENT_KEY", file=sys.stderr)
        sys.exit(1)

    resources = asyncio.run(connector.pull_all(limit=args.limit))

    saver = save_snapshot_incremental if args.incremental else save_snapshot
    path = saver(
        service="descope",
        profile=args.profile,
        resources=resources,
        connector_name=connector.name(),
        redacted=not args.no_redact,
    )
    print(f"Snapshot saved to {path}")


if __name__ == "__main__":
    main()
