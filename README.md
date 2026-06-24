# jamf_group_cleanup

Merges Jamf Pro groups. Adds all members from a source group into a target static group, then deletes the source. Supports both computer and mobile device groups (static or smart).

## What it does

1. Reads a `merge.yaml` config listing source → target group pairs
2. Resolves all group names/IDs via the Jamf Classic API and validates the config upfront:
   - Both groups must exist
   - Target must be a static group (smart groups can't have members added explicitly)
   - Source and target can't be the same group
3. In `--dry` mode: prints a plan showing what would be added/skipped — no API writes
4. In normal mode: PUTs the merged member list to the target, then DELETEs the source
   - If the source is a smart group, its current members are snapshotted and added
   - Source group is only deleted if the PUT succeeded
   - Failed merges are logged and skipped; subsequent entries still run

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

Copy `merge.yaml.example` to `merge.yaml` and define your merges:

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
```

**Fields:**

| Field | Required | Description |
|---|---|---|
| `source` | yes | Group name (string) or Jamf ID (integer) to merge from and delete |
| `target` | yes | Group name (string) or Jamf ID (integer) to merge into (must be static) |
| `type` | yes | `computer` or `mobile_device` |

> **Note:** Do not point two entries at the same target group in a single run — the second PUT will use a stale member snapshot and may produce unexpected results. Run them separately instead.

## Usage

```sh
# Preview what would happen (no changes)
./run.sh --dry

# Execute the merges
./run.sh
```

Exits with a non-zero code if any merge fails.

Logs are written to `logs/<timestamp>.log`. The last 8 logs are kept automatically.

## Output

```
[OK]   Old Staff Macs → All Staff Computers  (42 added, 3 already present)
[SKIP] Retired iPad Pool → All Student iPads  (0 new members, source not deleted)
[FAIL] Old Lab Macs → All Lab Computers       (PUT 500: internal server error)

2 succeeded, 1 skipped, 1 failed
```

| Status | Meaning |
|---|---|
| `OK` | Members added to target, source deleted |
| `SKIP` | Source had no new members; source not deleted |
| `FAIL` | PUT or DELETE failed after retry; source not deleted |

## Tests

```sh
pytest
```
