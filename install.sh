#!/bin/sh
# Install jamf_group_cleanup + dependencies on a new machine.
# Assumes: Homebrew and Git are already installed.
# Encrypted files (.env.age) should be placed in ~/Scripts/jamf_client/ before running.

set -e

SCRIPTS_DIR="$HOME/Scripts"
JAMF_CLIENT_DIR="$SCRIPTS_DIR/jamf_client"
PROJECT_DIR="$SCRIPTS_DIR/jamf_group_cleanup"

JAMF_CLIENT_REPO="https://github.com/azuda/jamf_client.git"
PROJECT_REPO="https://github.com/azuda/jamf_group_cleanup.git"

echo "==> Installing age"
brew install age

echo "==> Creating $SCRIPTS_DIR"
mkdir -p "$SCRIPTS_DIR"

echo "==> Cloning jamf_client"
if [ -d "$JAMF_CLIENT_DIR/.git" ]; then
  echo "    Already cloned, pulling latest"
  git -C "$JAMF_CLIENT_DIR" pull
else
	git clone "$JAMF_CLIENT_REPO" "$JAMF_CLIENT_DIR"
fi

echo "==> Cloning jamf_group_cleanup"
if [ -d "$PROJECT_DIR/.git" ]; then
	echo "    Already cloned, pulling latest"
	git -C "$PROJECT_DIR" pull
else
	git clone "$PROJECT_REPO" "$PROJECT_DIR"
fi

echo "==> Setting up Python virtual environment"
cd "$PROJECT_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

echo "==> Decrypting credentials"
AGE_FILE="$JAMF_CLIENT_DIR/.env.age"
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$AGE_FILE" ]; then
	echo "    WARNING: $AGE_FILE not found — copy it to $JAMF_CLIENT_DIR and then run:"
	echo "      age -d -i ~/.age/jamf.txt -o $ENV_FILE $AGE_FILE"
elif [ -f "$ENV_FILE" ]; then
	echo "    .env already exists, skipping decryption"
else
	age -d -i ~/.age/jamf.txt -o "$ENV_FILE" "$AGE_FILE"
	echo "    .env written"
fi

echo "==> Setting up config"
if [ ! -f "$PROJECT_DIR/config.yaml" ]; then
	cp "$PROJECT_DIR/config.yaml.example" "$PROJECT_DIR/config.yaml"
	echo "    config.yaml created from example — edit it before running"
else
	echo "    config.yaml already exists, skipping"
fi

echo ""
echo "Done. To run:"
echo "  cd $PROJECT_DIR"
echo "  ./run.sh merge --dry"
echo "  ./run.sh scope --dry"
