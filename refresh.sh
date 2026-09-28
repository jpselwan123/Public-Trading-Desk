#!/bin/bash
# Pull the account (read-only) from the broker .env names, Trading 212 unless it names another
# (broker.py), and rebuild the page. Same as the round sync button.
cd "$(dirname "$0")" && python3 broker.py && python3 build_desk.py
