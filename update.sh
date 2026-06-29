#!/bin/sh
# Update jamf_group_cleanup and its dependencies.
# Safe to run repeatedly — all steps are idempotent.

set -e

SCRIPTS_DIR="$HOME/Scripts"
JAMF_CLIENT_DIR="$SCRIPTS_DIR/jamf_client"
PROJECT_DIR="$SCRIPTS_DIR/jamf_group_cleanup"

echo "==> Pulling jamf_client"
if [ -d "$JAMF_CLIENT_DIR/.git" ]; then
  git -C "$JAMF_CLIENT_DIR" pull
else
  echo "    WARNING: $JAMF_CLIENT_DIR not found — run install.sh first"
fi

echo "==> Pulling jamf_group_cleanup"
git -C "$PROJECT_DIR" pull

echo "==> Syncing Python packages"
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip --quiet
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --quiet

echo ""
echo "Done."
