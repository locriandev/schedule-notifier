# Weekly Schedule Notifier

An OpenShift CronJob that posts weekly rotation schedules to Slack and manages Slack user group membership. Parses a repeating schedule table, notifies team members of their release artistry and focused work assignments, and automatically updates the @release-artists user group to include only those on release artistry duty.

## Deployment

### Prerequisites

- OpenShift cluster access
- Slack bot token with the following permissions:
  - `chat:write` - Send notifications to channels
  - `usergroups:read` - Read user group membership
  - `usergroups:write` - Update user group membership
- `SLACK_TOKEN` environment variable set

### Deploy

```bash
# Create project
oc apply -f manifests/project.yaml

# Create secret (requires SLACK_TOKEN env var)
export SLACK_TOKEN="xoxb-your-token-here"
envsubst < manifests/secret.yaml | oc apply -f -

# Deploy application and configuration
oc apply -f manifests/configmap.yaml
oc create configmap weekly-schedule-app --from-file=schedule_notifier.py -n weekly-schedule-notifier

# Deploy the CronJob (runs every Monday at 9 AM UTC)
oc apply -f manifests/cronjob.yaml

# Test with a one-off job
oc create -f manifests/job.yaml
```

## Configuration

Edit `manifests/configmap.yaml` to update:
- Schedule rotation table
- Slack channel
- Slack user group ID (e.g., @release-artists)
- User ID mappings

## Features

### Slack User Group Management

The system automatically manages the membership of a Slack user group (e.g., @release-artists):
- **Adds** users who are assigned to release artistry duty
- **Removes** managed users who move to focused work
- **Preserves** any members not in the `SLACK_USER_MAPPING` (manual additions are kept)

This ensures the @release-artists handle always mentions the correct people based on the current schedule.

**For detailed information about how user group management works, see [USER_GROUP_MANAGEMENT.md](USER_GROUP_MANAGEMENT.md)**

## Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export SCHEMA="path/to/schema.txt"
export SLACK_CHANNEL="#your-channel"
export SLACK_USER_MAPPING='{"Name": "U12345678"}'
export SLACK_USER_GROUP_ID="SQ2NYLU56"

# Test notification and user group update (dry run - no token needed)
# User group update happens automatically if SLACK_USER_GROUP_ID is set
python schedule_notifier.py --notify-slack --dry-run

# Dry run with token to see actual current state and changes
export SLACK_TOKEN="xoxb-your-token"
python schedule_notifier.py --notify-slack --dry-run

# View schedule for a specific date
python schedule_notifier.py --date "Feb 9, 2026" --pretty
```
