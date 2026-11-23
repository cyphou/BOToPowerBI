"""Generate disabled review drafts from declared BO schedules and subscriptions.

The drafts are not verified Power BI REST payloads and must not be used as
evidence of source-to-target operational equivalence.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── Frequency mapping ─────────────────────────────────────────────

FREQUENCY_MAP = {
    'daily': 'Daily',
    'weekly': 'Weekly',
}


def _parse_time(time_str):
    """Extract hour and minute from a valid HH:MM time string.

    Returns:
        tuple: (hour, minute), or None if the time is not valid.
    """
    if not isinstance(time_str, str):
        return None
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', time_str)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _map_weekday(source_day):
    """Map weekday name to PBI day index.

    PBI: Sunday=1, Monday=2, ..., Saturday=7.
    """
    mapping = {
        'Sunday': 1, 'Monday': 2, 'Tuesday': 3, 'Wednesday': 4,
        'Thursday': 5, 'Friday': 6, 'Saturday': 7,
    }
    return mapping.get(source_day, 2)  # default Monday


def generate_refresh_config(extract_tasks, schedules=None):
    """Generate a disabled review draft from one declared BO schedule.

    Args:
        extract_tasks: list[dict] — BO scheduled instances for an artifact.
            Each has: id, schedule (with frequency, time, weekDay), priority.
        schedules: list[dict] — optional full schedule objects for enrichment.

    Returns:
        dict: Disabled candidate fields and review notes. No remote operation is
        performed, and missing or unsupported values are not defaulted.
    """
    if extract_tasks is None or extract_tasks == []:
        return {
            'enabled': False,
            'notes': [
                'No BO scheduled instances were supplied; manual review is required '
                'before configuring refresh.'
            ],
        }

    config = {
        'enabled': False,
        'times': [],
        'notes': [
            'Manual review is required; this schedule draft is disabled and '
            'does not establish source or target equivalence.'
        ],
    }
    if not isinstance(extract_tasks, list):
        logger.warning("Scheduled instances are invalid: expected a list.")
        config['notes'].append('Scheduled instances are invalid; expected a list.')
        return config
    if len(extract_tasks) != 1:
        config['notes'].append(
            'Multiple schedules cannot be combined automatically; review each separately.'
        )
        return config

    task = extract_tasks[0]
    if not isinstance(task, dict):
        logger.warning("Scheduled instance is invalid: expected an object.")
        config['notes'].append('Scheduled instance is invalid; expected an object.')
        return config
    sched = task.get('schedule')
    if not sched and task.get('schedule_id'):
        if schedules is not None and (
            not isinstance(schedules, list)
            or any(not isinstance(s, dict) for s in schedules)
        ):
            logger.warning("Schedule lookup is invalid: expected a list of objects.")
            config['notes'].append('Schedule lookup is invalid; expected a list of objects.')
            return config
        matches = [s for s in (schedules if schedules is not None else [])
                   if s.get('id') == task['schedule_id']]
        if len(matches) != 1:
            config['notes'].append('Schedule reference is missing or ambiguous.')
            return config
        sched = matches[0]
    if sched is None:
        sched = task
    if not isinstance(sched, dict):
        config['notes'].append('Schedule details are missing or invalid.')
        return config

    details = sched.get('frequencyDetails', sched)
    if not isinstance(details, dict):
        config['notes'].append('Frequency details are invalid and were not interpreted.')
        details = {}

    frequency = sched.get('frequency', sched.get('type'))
    mapped = FREQUENCY_MAP.get(frequency.casefold()) if isinstance(frequency, str) else None
    if mapped:
        config['frequency'] = mapped
    else:
        config['notes'].append('Schedule frequency is missing or unsupported.')

    start = details.get('start', details.get('time', sched.get('time')))
    time = _parse_time(start)
    if time is None:
        config['notes'].append('Schedule time is missing or invalid; no time was selected.')
    else:
        config['times'] = [f'{time[0]:02d}:{time[1]:02d}']

    zone = sched.get('localTimeZoneId', sched.get('timezone'))
    if isinstance(zone, str) and zone.strip():
        config['localTimeZoneId'] = zone
        config['notes'].append('Verify the declared time zone against the target environment.')
    else:
        config['notes'].append('Schedule time zone is missing or invalid.')

    intervals = details.get('intervals', {})
    if not isinstance(intervals, dict):
        config['notes'].append('Schedule intervals require manual review.')
        intervals = {}
    if any(key != 'weekDay' for key in intervals):
        config['notes'].append('Additional schedule intervals require manual review.')
    if mapped != 'Weekly' and (
        intervals.get('weekDay') or details.get('weekDay') or sched.get('weekDay')
    ):
        config['notes'].append('Declared weekday intervals require manual review.')

    if mapped == 'Weekly':
        weekdays = intervals.get('weekDay', details.get('weekDay', sched.get('weekDay')))
        if isinstance(weekdays, str):
            weekdays = [weekdays]
        valid_days = {'Sunday', 'Monday', 'Tuesday', 'Wednesday',
                      'Thursday', 'Friday', 'Saturday'}
        if (isinstance(weekdays, list) and weekdays
                and all(isinstance(day, str) and day in valid_days for day in weekdays)):
            config['days'] = list(dict.fromkeys(weekdays))
        else:
            if isinstance(weekdays, list):
                known_days = [day for day in weekdays
                              if isinstance(day, str) and day in valid_days]
                if known_days:
                    config['days'] = list(dict.fromkeys(known_days))
            config['notes'].append(
                'Weekly schedule days are missing or invalid; review the full declaration.'
            )

    return config


def generate_subscription_config(subscriptions):
    """Generate disabled subscription review drafts from BO declarations.

    Args:
        subscriptions: list[dict] — BO subscription objects.
            Each has: id, subject, user (name, email), schedule, content.

    Returns:
        list[dict]: Disabled subscription candidates with review notes.
    """
    if subscriptions is None or subscriptions == []:
        return []
    if not isinstance(subscriptions, list):
        raise ValueError("Subscriptions must be a list")

    results = []
    for sub in subscriptions:
        if not isinstance(sub, dict):
            raise ValueError("A subscription must be an object")
        subject = sub.get('subject') or sub.get('name')
        user = sub.get('user', {})
        if not isinstance(user, dict):
            raise ValueError("Subscription user must be an object")
        recipients = sub.get('recipients', [])
        if not isinstance(recipients, list) or any(
            not isinstance(recipient, str) or not recipient.strip()
            for recipient in recipients
        ):
            raise ValueError("Subscription recipients must be a list of nonempty strings")
        email = user.get('email')
        if email is not None:
            if not isinstance(email, str) or not email.strip():
                raise ValueError("Subscription email must be a nonempty string")
            recipients = list(dict.fromkeys([*recipients, email]))

        schedule = sub.get('schedule')
        draft = generate_refresh_config([{'schedule': schedule if schedule is not None else sub}])
        notes = draft['notes']
        if not isinstance(subject, str) or not subject.strip():
            subject = 'Untitled'
            notes.append('Subscription title is missing; a placeholder was used.')
        if not recipients:
            notes.append('Subscription recipients are missing and require manual review.')
        else:
            notes.append('Subscription recipients are unverified and require manual review.')

        config = {
            'title': subject,
            'recipients': recipients,
            'enabled': False,
            'notes': notes,
        }
        for key in ('frequency', 'days', 'localTimeZoneId'):
            if key in draft:
                config[key] = draft[key]
        if draft['times']:
            config['time'] = draft['times'][0]
        results.append(config)

    return results


def generate_refresh_json(extract_tasks, subscriptions=None, schedules=None):
    """Generate combined refresh + subscription JSON artifact.

    Args:
        extract_tasks: BO scheduled instances for an artifact.
        subscriptions: BO subscriptions for an artifact.
        schedules: Full schedule objects for enrichment.

    Returns:
        dict: Combined config with 'refresh' and 'subscriptions' keys.
    """
    refresh = generate_refresh_config(extract_tasks, schedules)
    subs = generate_subscription_config(subscriptions)

    return {
        'refresh': refresh,
        'subscriptions': subs,
        'migration_notes': [
            'Schedules and subscriptions are disabled review drafts, not deployed configuration.',
            'Review source semantics, target time zone, identities, licensing and gateway configuration.',
        ],
    }
