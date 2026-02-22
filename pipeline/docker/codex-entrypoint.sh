#!/bin/bash
# Codex entrypoint: auto-login with API key before running commands
if [ -n "$OPENAI_API_KEY" ]; then
    printenv OPENAI_API_KEY | codex login --with-api-key >/dev/null 2>&1
fi
exec codex "$@"
