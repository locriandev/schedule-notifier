# Slack User Group Management

## Overview

The schedule-notifier now automatically manages the @release-artists Slack user group membership based on who is assigned to release artistry duty each week.

## How It Works

### Managed vs. Non-Managed Members

The system distinguishes between two types of user group members:

1. **Managed Members**: Users listed in `SLACK_USER_MAPPING` configmap
   - These are the team members who rotate through release artistry and focused work
   - The system automatically adds/removes these users based on the schedule

2. **Non-Managed Members**: Users NOT in `SLACK_USER_MAPPING`
   - These could be managers, observers, or others manually added to the group
   - The system PRESERVES these members - they are never removed

### Update Logic

When the schedule updates (every Monday at 9 AM UTC):

1. **Fetch Current Members**: Get all current @release-artists group members
2. **Identify Managed Users**: Find which members are in our `SLACK_USER_MAPPING`
3. **Preserve Non-Managed**: Keep all members not in the mapping
4. **Add Release Artistry Team**: Add all users currently on release artistry duty
5. **Remove Managed Users**: Remove managed users who moved to focused work
6. **Update Group**: Apply the new membership list

### Example

**Initial State:**
- User Group Members: `[Alice, Bob, Charlie, Manager]`
- SLACK_USER_MAPPING: `{Alice, Bob, Charlie}`
- Manager is NOT in mapping (manually added)

**This Week's Schedule:**
- Release Artistry: Alice, Bob
- Focused Work: Charlie

**After Update:**
- User Group Members: `[Alice, Bob, Manager]`
- Charlie removed (managed user, now on focused work)
- Manager preserved (non-managed user)

**Next Week's Schedule:**
- Release Artistry: Charlie, Alice
- Focused Work: Bob

**After Update:**
- User Group Members: `[Alice, Charlie, Manager]`
- Charlie added back (now on release artistry)
- Bob removed (moved to focused work)
- Manager still preserved

## Configuration

### Required Environment Variables

```yaml
SLACK_USER_GROUP_ID: "SQ2NYLU56"  # The user group ID to manage
SLACK_USER_MAPPING: |
  {
    "Fabio": "U0A0N29FUQK",
    "Michael": "U04JLK3F04R",
    "Luis": "UDWSG7LSK",
    "Daniele": "U02NV63HBHV",
    "Joep": "UMDFFDKU5"
  }
```

### Required Slack Permissions

Your Slack bot token needs these scopes:
- `chat:write` - Send notifications
- `usergroups:read` - Read user group membership
- `usergroups:write` - Update user group membership

## Testing

### Dry Run Mode

Test the functionality without making actual changes:

```bash
export SLACK_CHANNEL="#test-channel"
export SLACK_USER_GROUP_ID="SQ2NYLU56"
export SLACK_USER_MAPPING='{"Alice": "U111", "Bob": "U222", "Charlie": "U333"}'
export SCHEMA="/path/to/schema.txt"

# Test without a token (simulates actions, cannot fetch current state)
python schedule_notifier.py --notify-slack --dry-run

# Test with a token (fetches current state to show actual changes)
export SLACK_TOKEN="xoxb-your-token"
python schedule_notifier.py --notify-slack --dry-run
```

In dry-run mode:
- **Without SLACK_TOKEN**: Simulates all actions, shows what members would be added
- **With SLACK_TOKEN**: Fetches current user group members to show exact changes (added/removed)
- The system WILL NOT send Slack messages
- The system WILL NOT update the user group
- All operations are logged with `[DRY RUN]` prefix

### Manual Testing

To test the user group update for a specific date:

```bash
python schedule_notifier.py --date "Feb 16, 2026" --notify-slack --dry-run
```

### Disabling User Group Management

To disable automatic user group updates, simply omit `SLACK_USER_GROUP_ID` from the configuration. The system will only send notifications without managing group membership.

## Troubleshooting

### "No Slack user ID found for 'Name'"

This warning means someone in the schedule is not in `SLACK_USER_MAPPING`. They won't be added to the user group. Add them to the mapping in the configmap.

### "User group is already up to date"

The current membership already matches the schedule. No changes needed.

### "Failed to get user group members" or "Failed to update user group"

Check that:
1. `SLACK_TOKEN` has the correct permissions (`usergroups:read`, `usergroups:write`)
2. `SLACK_USER_GROUP_ID` is correct
3. The bot has access to manage the user group

## Architecture Notes

The user group update happens AFTER sending the Slack notification. This ensures the notification is sent first, then the group membership is updated for future mentions.

The system is idempotent - running it multiple times with the same schedule won't cause issues. It only updates the group if changes are needed.

In dry-run mode without a SLACK_TOKEN, the system will simulate all operations but cannot fetch the current user group state to show exact changes.
