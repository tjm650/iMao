#!/usr/bin/env python3
"""Create an wiMao administrator without exposing a default web registration route."""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.admin import create_admin
from database.database import initialize_database


def main():
    parser = argparse.ArgumentParser(description="Create an wiMao administrator account")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=["admin", "manager", "operator", "viewer"], default="admin")
    args = parser.parse_args()
    password = getpass.getpass("Administrator password (12+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    initialize_database()
    create_admin(args.username, password, args.role)
    print(f"Administrator '{args.username}' created.")


if __name__ == "__main__":
    main()
