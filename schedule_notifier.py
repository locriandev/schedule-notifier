#!/usr/bin/env python3

"""
This script parses a weekly rotation schedule and returns the current week's assignments
as JSON. The schedule includes release artistry and focused work assignments. The schedule
repeats in a cycle, so dates beyond the defined schedule will use the repeating pattern.

The script requires the SCHEMA environment variable to be set to the path of the schema file.

Environment Variables:
    SCHEMA: Path to the schema file (required)
    SLACK_TOKEN: Slack API token (optional, for notifications)
    SLACK_CHANNEL: Slack channel name (optional, for notifications)
                   Example: '#art-release'
    SLACK_USER_MAPPING: JSON mapping from display names to Slack user IDs (optional)
                        Example: '{"Daniele": "U12345678", "Fabio": "U87654321"}'
    SLACK_USER_GROUP_ID: Slack user group ID to manage (optional)
                         Example: 'SQ2NYLU56'

Examples:
    # Set the SCHEMA environment variable
    export SCHEMA=/path/to/schema.txt

    # Display current week's schedule
    python schedule_notifier.py

    # Display schedule for a specific date
    python schedule_notifier.py --date "2026-04-13"

    # Use a custom schedule file (overrides SCHEMA env var)
    python schedule_notifier.py --schedule-file my_schedule.txt

    # Send Slack notification
    export SLACK_TOKEN=xoxb-your-token
    export SLACK_CHANNEL='#art-release'
    export SLACK_USER_MAPPING='{"Fabio": "U12345678", "Michael": "U23456789", "Luis": "U34567890", "Daniele": "U45678901", "Joep": "U56789012"}'
    python schedule_notifier.py --notify-slack

    # Update Slack user group with release artistry team (preserves non-managed members)
    # This happens automatically when SLACK_USER_GROUP_ID is set
    export SLACK_USER_GROUP_ID='SQ2NYLU56'
    python schedule_notifier.py --notify-slack

    # Dry run mode (logs Slack messages without sending)
    python schedule_notifier.py --notify-slack --dry-run

Sample input:
    ├───────────────┼────────────────────────┼──────────────────┤
    | Week starting | Release artistry (3)   | Focused work (2) |
    ├───────────────┼────────────────────────┼──────────────────┤
    | Feb 9, 2026   | Fabio, Michael, Luis   | Daniele, Joep    |
    ├───────────────┼────────────────────────┼──────────────────┤
    | Feb 16, 2026  | Daniele, Joep, Fabio   | Michael, Luis    |
    ├───────────────┼────────────────────────┼──────────────────┤
    | Feb 23, 2026  | Michael, Luis, Daniele | Fabio, Joep      |
    ├───────────────┼────────────────────────┼──────────────────┤
    | Mar 2, 2026   | Joep, Fabio, Michael   | Luis, Daniele    |
    ├───────────────┼────────────────────────┼──────────────────┤
    | Mar 9, 2026   | Luis, Daniele, Joep    | Fabio, Michael   |
    ├───────────────┼────────────────────────┼──────────────────┤
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class ScheduleNotifier:
    """
    Manages weekly rotation schedules with support for repeating cycles and Slack notifications.
    """

    def __init__(self, schedule_file: Optional[Path] = None, schedule_content: Optional[str] = None, dry_run: bool = False):
        """
        Initialize the ScheduleNotifier.

        Arg(s):
            schedule_file (Optional[Path]): Path to the schedule file.
            schedule_content (Optional[str]): Schedule content as a string (alternative to schedule_file).
            dry_run (bool): If True, only log Slack messages instead of sending them.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.schedule_file = schedule_file
        self.schedule_content = schedule_content
        self.dry_run = dry_run
        self.schedule: List[Tuple[datetime, List[str], List[str]]] = []
        self.slack_client: Optional[WebClient] = None
        self.slack_user_mapping: Dict[str, str] = {}
        self.slack_user_group_id: Optional[str] = None
        self._load_schedule()
        self._load_slack_user_mapping()
        self._load_slack_user_group_id()

    def new_slack_client(self, token: Optional[str] = None, channel: Optional[str] = None) -> None:
        """
        Create a new Slack client and store it as an attribute.

        Arg(s):
            token (Optional[str]): Slack API token. If None, reads from SLACK_TOKEN env var.
            channel (Optional[str]): Slack channel. If None, reads from SLACK_CHANNEL env var.
        """
        if not token:
            token = os.environ.get("SLACK_TOKEN")
            if not token and not self.dry_run:
                raise ValueError("SLACK_TOKEN environment variable is not set")

        if not channel:
            channel = os.environ.get("SLACK_CHANNEL")
            if not channel:
                raise ValueError("SLACK_CHANNEL environment variable is not set")

        # Require SLACK_USER_MAPPING for proper user mentions
        if not self.slack_user_mapping:
            raise ValueError(
                "SLACK_USER_MAPPING environment variable is not set. "
                "This is required for proper Slack user mentions. "
                "Set it to a JSON mapping like: '{\"Name\": \"U12345678\"}'"
            )

        self.slack_channel = channel

        # Only create real client if we have a token (needed for fetching current state even in dry-run)
        if token:
            self.slack_client = WebClient(token=token)
        else:
            self.slack_client = None
            self.logger.info("[DRY RUN] No SLACK_TOKEN provided, will simulate without fetching current state")

    @staticmethod
    def _parse_schedule_line(line: str) -> Optional[Tuple[datetime, List[str], List[str]]]:
        """
        Parse a single schedule line and extract the date and people assignments.

        Arg(s):
            line (str): A line from the schedule table.

        Return Value(s):
            Optional[Tuple[datetime, List[str], List[str]]]: Tuple of (date, release_artistry, focused_work)
                or None if the line doesn't contain schedule data.
        """
        # Skip separator lines and header
        if line.strip().startswith('├') or line.strip().startswith('|') and 'Week starting' in line:
            return None

        # Match lines like: | Feb 9, 2026   | Fabio, Michael, Luis   | Daniele, Joep    |
        match = re.match(r'\|\s*([A-Za-z]+\s+\d+,\s+\d+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|', line)
        if not match:
            return None

        date_str = match.group(1).strip()
        release_artistry_str = match.group(2).strip()
        focused_work_str = match.group(3).strip()

        # Parse the date
        try:
            week_date = datetime.strptime(date_str, "%b %d, %Y")
        except ValueError:
            return None

        # Parse the people lists
        release_artistry = [name.strip() for name in release_artistry_str.split(',')]
        focused_work = [name.strip() for name in focused_work_str.split(',')]

        return week_date, release_artistry, focused_work

    def _load_schedule(self) -> None:
        """
        Load and parse the schedule from the file or content string.
        """
        lines = []

        if self.schedule_content:
            # Parse from content string
            lines = self.schedule_content.splitlines()
        elif self.schedule_file:
            # Parse from file
            if not self.schedule_file.exists():
                raise FileNotFoundError(f"Schedule file not found: {self.schedule_file}")
            with open(self.schedule_file, 'r') as f:
                lines = f.readlines()
        else:
            raise ValueError("Either schedule_file or schedule_content must be provided")

        for line in lines:
            parsed = self._parse_schedule_line(line)
            if parsed:
                self.schedule.append(parsed)

        if not self.schedule:
            source = "content" if self.schedule_content else str(self.schedule_file)
            raise ValueError(f"No valid schedule entries found in {source}")

        # Sort schedule by date to ensure proper ordering
        self.schedule = sorted(self.schedule, key=lambda x: x[0])

    def _load_slack_user_mapping(self) -> None:
        """
        Load Slack user ID mapping from environment variable.
        """
        mapping_str = os.environ.get("SLACK_USER_MAPPING")
        if mapping_str:
            try:
                self.slack_user_mapping = json.loads(mapping_str)
                self.logger.info("Loaded Slack user mapping for %d users", len(self.slack_user_mapping))
            except json.JSONDecodeError as e:
                self.logger.warning("Failed to parse SLACK_USER_MAPPING: %s", e)
                self.slack_user_mapping = {}

    def _load_slack_user_group_id(self) -> None:
        """
        Load Slack user group ID from environment variable.
        """
        self.slack_user_group_id = os.environ.get("SLACK_USER_GROUP_ID")
        if self.slack_user_group_id:
            self.logger.info("Loaded Slack user group ID: %s", self.slack_user_group_id)

    @staticmethod
    def _calculate_week_in_cycle(schedule_start: datetime, target_date: datetime, cycle_length: int) -> int:
        """
        Calculate which week in the cycle the target date corresponds to.

        Arg(s):
            schedule_start (datetime): The start date of the first week in the schedule.
            target_date (datetime): The date to calculate the week for.
            cycle_length (int): The number of weeks in the rotation cycle.

        Return Value(s):
            int: The week index in the cycle (0 to cycle_length-1).
        """
        days_diff = (target_date - schedule_start).days
        weeks_diff = days_diff // 7
        return weeks_diff % cycle_length

    def get_schedule_for_date(self, target_date: datetime) -> Dict[str, List[str]]:
        """
        Get the schedule for a specific date.

        Arg(s):
            target_date (datetime): The date to get the schedule for.

        Return Value(s):
            Dict[str, List[str]]: Dictionary containing release_artistry and focused_work assignments.
        """
        if not self.schedule:
            raise ValueError("No schedule data available")

        schedule_start = self.schedule[0][0]
        cycle_length = len(self.schedule)

        # Calculate which week in the cycle this date corresponds to
        week_index = self._calculate_week_in_cycle(schedule_start, target_date, cycle_length)

        # Get the schedule for that week in the cycle
        _, release_artistry, focused_work = self.schedule[week_index]

        return {"release_artistry": release_artistry, "focused_work": focused_work}

    def get_cycle_info(self) -> Dict[str, any]:
        """
        Get information about the schedule cycle.

        Return Value(s):
            Dict[str, any]: Dictionary containing cycle information.
        """
        if not self.schedule:
            return {}

        return {
            "cycle_length": len(self.schedule),
            "start_date": self.schedule[0][0].strftime("%b %d, %Y"),
            "end_date": self.schedule[-1][0].strftime("%b %d, %Y"),
        }

    def _format_people_list(self, people: List[str]) -> str:
        """
        Convert a list of people names to Slack mention format.

        Arg(s):
            people (List[str]): List of people names.

        Return Value(s):
            str: Comma-separated list with proper Slack mentions.
        """
        formatted = []
        for name in people:
            if name in self.slack_user_mapping:
                # Use proper Slack mention format with user ID
                user_id = self.slack_user_mapping[name]
                formatted.append(f"<@{user_id}>")
            else:
                # Fall back to @name if no mapping found
                formatted.append(f"@{name}")
                self.logger.warning("No Slack user ID found for '%s', using @mention fallback", name)

        return ", ".join(formatted)

    def _get_managed_user_ids(self) -> set:
        """
        Get the set of user IDs that are managed by this schedule system.

        Return Value(s):
            set: Set of Slack user IDs for users in the SLACK_USER_MAPPING.
        """
        return set(self.slack_user_mapping.values())

    def _get_user_group_members(self) -> List[str]:
        """
        Get the current members of the Slack user group.

        Return Value(s):
            List[str]: List of Slack user IDs in the user group.
        """
        if not self.slack_client:
            self.logger.info("[DRY RUN] No Slack client available, cannot fetch current user group members")
            return []

        try:
            response = self.slack_client.usergroups_users_list(usergroup=self.slack_user_group_id)
            members = response.get("users", [])
            log_prefix = "[DRY RUN] " if self.dry_run else ""
            self.logger.info("%sCurrent user group has %d members: %s", log_prefix, len(members), members)
            return members

        except SlackApiError as e:
            self.logger.error("Failed to get user group members: %s", e.response["error"])
            raise

    def _update_user_group(self, release_artistry_names: List[str]) -> None:
        """
        Update the Slack user group with the current release artistry team.
        Preserves any members that are not managed by this system.

        Arg(s):
            release_artistry_names (List[str]): Names of people on release artistry duty.
        """
        if not self.slack_user_group_id:
            self.logger.info("No SLACK_USER_GROUP_ID configured, skipping user group update")
            return

        # Get IDs of users who should be in the group (on release artistry)
        release_artistry_ids = set()
        for name in release_artistry_names:
            if name in self.slack_user_mapping:
                release_artistry_ids.add(self.slack_user_mapping[name])
            else:
                self.logger.warning("No Slack user ID found for '%s', cannot add to user group", name)

        # Get current members (may be empty if no Slack client available)
        current_members = set(self._get_user_group_members())

        # Identify which users are managed by this system
        managed_user_ids = self._get_managed_user_ids()

        # Preserve non-managed members (users not in our SLACK_USER_MAPPING)
        preserved_members = current_members - managed_user_ids

        # Build the new member list: preserved members + release artistry team
        new_members = list(preserved_members | release_artistry_ids)

        if self.dry_run:
            self.logger.info("[DRY RUN] Would update user group %s", self.slack_user_group_id)
            if current_members:
                self.logger.info("[DRY RUN] Preserved %d non-managed members: %s", len(preserved_members), preserved_members if preserved_members else "none")
                self.logger.info("[DRY RUN] Release artistry members to add: %s", release_artistry_ids)
                self.logger.info("[DRY RUN] New member list would be: %s", new_members)

                # Show what would change
                added = release_artistry_ids - current_members
                removed = (current_members & managed_user_ids) - release_artistry_ids
                if added:
                    self.logger.info("[DRY RUN] Would add to group: %s", added)
                if removed:
                    self.logger.info("[DRY RUN] Would remove from group: %s", removed)
                if not added and not removed:
                    self.logger.info("[DRY RUN] No changes needed, group already up to date")
            else:
                self.logger.info("[DRY RUN] Release artistry members that would be added: %s", release_artistry_ids)
                self.logger.info("[DRY RUN] (Cannot show full diff without current member list)")
            return

        # Check if update is needed
        if current_members == set(new_members):
            self.logger.info("User group is already up to date, no changes needed")
            return

        try:
            response = self.slack_client.usergroups_users_update(
                usergroup=self.slack_user_group_id,
                users=",".join(new_members)
            )
            self.logger.info("User group updated successfully")
            self.logger.info("Preserved %d non-managed members", len(preserved_members))
            self.logger.info("Added %d release artistry members", len(release_artistry_ids))

            # Log the changes for visibility
            added = release_artistry_ids - current_members
            removed = (current_members & managed_user_ids) - release_artistry_ids
            if added:
                self.logger.info("Added to group: %s", added)
            if removed:
                self.logger.info("Removed from group: %s", removed)

        except SlackApiError as e:
            self.logger.error("Failed to update user group: %s", e.response["error"])
            raise

    def send_schedule_notification(self, schedule_data: Dict[str, List[str]], target_date: datetime) -> None:
        """
        Send a Slack notification about the current week's schedule.

        Arg(s):
            schedule_data (Dict[str, List[str]]): Schedule data with release_artistry and focused_work.
            target_date (datetime): The date for this schedule.
        """
        release_artistry = self._format_people_list(schedule_data["release_artistry"])
        focused_work = self._format_people_list(schedule_data["focused_work"])

        week_date = target_date.strftime("%b %d, %Y")

        message = (
            f":calendar: *Weekly Schedule for week of {week_date}*\n\n"
            f":hammer_and_wrench: *Release Artistry:* {release_artistry}\n"
            f":dart: *Focused Work:* {focused_work}"
        )

        if self.dry_run:
            self.logger.info("[DRY RUN] Would send to %s: %s", self.slack_channel, message)
            return

        try:
            response = self.slack_client.chat_postMessage(
                channel=self.slack_channel,
                text=message,
                username="schedule-bot",
                icon_emoji=":calendar:",
            )
            self.logger.info("Slack message sent successfully: %s", response["ts"])
        except SlackApiError as e:
            self.logger.error("Failed to send Slack message: %s", e.response["error"])
            raise


@click.command()
@click.option('--date', type=str, help='Target date in format "Feb 9, 2026" (defaults to today)', default=None)
@click.option(
    '--schedule-file',
    type=click.Path(exists=False, path_type=Path),
    help='Path to a custom schedule file (overrides SCHEMA env var)',
    default=None,
)
@click.option('--pretty', is_flag=True, help='Pretty-print the JSON output', default=False)
@click.option('--notify-slack', is_flag=True, help='Send Slack notification about the schedule', default=False)
@click.option('--dry-run', is_flag=True, help='Dry run mode (logs Slack messages instead of sending)', default=False)
def main(
    date: Optional[str], schedule_file: Optional[Path], pretty: bool, notify_slack: bool, dry_run: bool
) -> None:
    """
    Get the current week's rotation schedule.

    The script requires the SCHEMA environment variable to be set unless
    --schedule-file is provided.

    For Slack notifications, set:
    - SLACK_TOKEN: Slack API token
    - SLACK_CHANNEL: Slack channel name (e.g., '#art-release')
    """
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    try:
        # Determine target date
        if date:
            try:
                target_date = datetime.strptime(date, "%b %d, %Y")
            except ValueError:
                click.echo(f"Error: Invalid date format '{date}'. Use format like 'Feb 9, 2026'", err=True)
                raise click.Abort()
        else:
            target_date = datetime.now()

        # Determine schedule file or content
        schedule_content = None
        if schedule_file is None:
            schema_env = os.environ.get("SCHEMA")
            if not schema_env:
                click.echo(
                    "Error: SCHEMA environment variable is not set. Please set it to the path of the schema file.",
                    err=True,
                )
                raise click.Abort()

            # Check if SCHEMA is a file path or actual content
            # If it contains newlines or starts with table characters, treat it as content
            if '\n' in schema_env or schema_env.strip().startswith('├') or schema_env.strip().startswith('|'):
                schedule_content = schema_env
            else:
                schedule_file = Path(schema_env)

        # Create schedule notifier and get schedule
        notifier = ScheduleNotifier(schedule_file=schedule_file, schedule_content=schedule_content, dry_run=dry_run)
        schedule_data = notifier.get_schedule_for_date(target_date)

        result = {"schedule": schedule_data}

        # Output result
        if pretty:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(json.dumps(result))

        # Send Slack notification if requested
        if notify_slack:
            notifier.new_slack_client()
            notifier.send_schedule_notification(schedule_data, target_date)
            notifier._update_user_group(schedule_data["release_artistry"])
            if dry_run:
                click.echo(f"[DRY RUN] Would send Slack notification to {notifier.slack_channel}")
            else:
                click.echo(f"Slack notification sent to {notifier.slack_channel}")

    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    main()
