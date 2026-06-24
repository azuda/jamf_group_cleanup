# jamf_group_cleanup

Two subcommands for managing Jamf Pro group references:

- **`merge`** — adds all members from a source group into a target static group, then deletes the source
- **`scope`** — replaces a source group with a target group in all policy and config profile scopes (does not delete the source group)

## Setup

Requires `jamf_client` from `../jamf_client`.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your Jamf credentials:

```
JAMF_URL=https://yourschool.jamfcloud.com
CLIENT_ID=your-api-client-id
CLIENT_SECRET=your-api-client-secret
```

Credentials are stored encrypted at `../jamf_client/.env.age`. Decrypt to get your `.env`:

```sh
age --decrypt -o .env ../jamf_client/.env.age
```

`age` can be installed via Homebrew if needed:

```sh
brew install age
```

## Config

Copy `config.yaml.example` to `config.yaml` and define your operations:

```yaml
merges:
  # Merge by name (static → static)
  - source: "Old Staff Macs"
    target: "All Staff Computers"
    type: computer

  # Merge by Jamf ID (useful for names with special characters)
  - source: 4821
    target: "All Student iPads"
    type: mobile_device

  # Smart group as source — members are snapshotted at run time
  - source: "Retired iPad Smart Group"
    target: "All Student iPads"
    type: mobile_device

scopes:
  # Replace source group with target in all policy/profile scopes (computers)
  - source: "Old Staff Macs"
    target: "All Staff Computers"
    type: computer

  # Replace source group in mobile device profile scopes
  - source: "Old iPad Group"
    target: "All Student iPads"
    type: mobile_device
```

**Fields (both `merges` and `scopes` entries):**

| Field | Required | Description |
|---|---|---|
| `source` | yes | Group name (string) or Jamf ID (integer) |
| `target` | yes | Group name (string) or Jamf ID (integer) |
| `type` | yes | `computer` or `mobile_device` |

`merge` and `scope` subcommands are independent — each reads only its own config section.

## Usage

```sh
# Merge subcommand
./run.sh merge          # execute merges
./run.sh merge --dry    # preview merges, no changes

# Scope subcommand
./run.sh scope          # replace group references in scopes
./run.sh scope --dry    # preview scope changes, no changes
```

Both subcommands exit with a non-zero code if any entry fails.

Logs are written to `logs/<timestamp>.log`. The last 8 logs are kept automatically.

## Output

### merge

```
[OK]   Old Staff Macs → All Staff Computers  (42 added, 3 already present)
[SKIP] Retired iPad Pool → All Student iPads  (0 new members, source not deleted)
[FAIL] Old Lab Macs → All Lab Computers       (PUT 500: internal server error)

1 succeeded, 1 skipped, 1 failed
```

| Status | Meaning |
|---|---|
| `OK` | Members added to target, source deleted |
| `SKIP` | Source had no new members; source not deleted |
| `FAIL` | PUT or DELETE failed after retry; source not deleted |

### scope

```
[OK]   Old Group → New Group  (4 objects updated)
[SKIP] Old iPad Group → All iPads  (source group not found in any scope)
[FAIL] Old Lab Group → New Lab Group  (PUT 'Deploy Xcode' 500: error — source not deleted)

1 succeeded, 1 skipped, 1 failed
```

| Status | Meaning |
|---|---|
| `OK` | Source group replaced with target in all matching policy/profile scopes |
| `SKIP` | Source group not found in any scope; no changes made |
| `FAIL` | One or more PUT requests failed after retry; partially updated entries are not rolled back |

> **Note:** The `scope` subcommand never deletes the source group. It only replaces references in policy/profile scopes.

## Tests

```sh
pytest
```
