# Weekly Schedule Notifier

An OpenShift CronJob that posts weekly rotation schedules to Slack. Parses a repeating schedule table and notifies team members of their release artistry and focused work assignments.

## Deployment

### Prerequisites

- OpenShift cluster access
- Slack bot token with `chat:write` permissions
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
- User ID mappings

## Local Testing

```bash
export SCHEMA="path/to/schema.txt"
export SLACK_TOKEN="xoxb-your-token"
export SLACK_CHANNEL="#your-channel"
export SLACK_USER_MAPPING='{"Name": "U12345678"}'

python schedule_notifier.py --notify-slack --dry-run
```
