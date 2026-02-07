#!/usr/bin/bash

# Force local to match remote exactly
git fetch --all
git reset --hard origin/main

# Ensure all scripts stay executable
chmod +x *.sh
