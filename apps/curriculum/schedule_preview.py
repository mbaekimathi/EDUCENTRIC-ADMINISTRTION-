DAY_MINUTES = 24 * 60
DAY_ORDER = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
WEEKDAY_LABELS = {
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
    "SAT": "Saturday",
    "SUN": "Sunday",
    "EXM": "Exam day",
}
EXAM_DAY_CODE = "EXM"


def to_minutes(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return value.hour * 60 + value.minute


def format_minutes(total):
    total = int(total) % DAY_MINUTES
    return f"{total // 60:02d}:{total % 60:02d}"


def minutes_to_time(total):
    from datetime import time as datetime_time

    total = int(total) % DAY_MINUTES
    return datetime_time(total // 60, total % 60)


def ordered_day_labels(study_days):
    selected = {str(day).upper() for day in (study_days or [])}
    return [WEEKDAY_LABELS[day] for day in DAY_ORDER if day in selected]


def build_schedule_preview(
    first_class_start,
    lesson_duration,
    activities,
    last_class_end=None,
    study_days=None,
    period_label="Lesson",
    day_labels=None,
    start_caption="first class",
    end_caption="lesson end time",
):
    """Build a day timetable using full periods in every gap."""
    issues = []
    blocks = []
    days = list(day_labels) if day_labels is not None else ordered_day_labels(study_days)
    start = to_minutes(first_class_start)
    day_end = to_minutes(last_class_end)
    try:
        lesson = int(lesson_duration or 0)
    except (TypeError, ValueError):
        lesson = 0

    items = []
    for raw in activities:
        if hasattr(raw, "name"):
            name = (raw.name or "").strip()
            start_m = to_minutes(raw.start_time)
            duration = int(getattr(raw, "duration_minutes", 0) or 0)
        else:
            name = (raw.get("name") or "").strip()
            start_m = raw.get("start")
            duration = int(raw.get("duration") or 0)
        if start_m is None or duration <= 0:
            continue
        items.append(
            {
                "name": name or "ACTIVITY",
                "start": start_m,
                "end": start_m + duration,
                "duration": duration,
                "collision": False,
            }
        )

    items.sort(key=lambda item: (item["start"], item["name"]))

    for index, current in enumerate(items):
        for other in items[index + 1 :]:
            if current["start"] < other["end"] and other["start"] < current["end"]:
                overlap_start = max(current["start"], other["start"])
                overlap_end = min(current["end"], other["end"])
                current["collision"] = True
                other["collision"] = True
                issues.append(
                    {
                        "type": "collision",
                        "message": (
                            f"{current['name']} overlaps {other['name']} from "
                            f"{format_minutes(overlap_start)} to {format_minutes(overlap_end)}."
                        ),
                    }
                )

    if start is None or lesson <= 0 or day_end is None:
        return {
            "blocks": blocks,
            "issues": _unique_issues(issues),
            "ready": False,
            "days": days,
        }

    if day_end <= start:
        issues.append(
            {
                "type": "collision",
                "message": f"{end_caption.capitalize()} must be later than {start_caption}.",
            }
        )
        return {
            "blocks": blocks,
            "issues": _unique_issues(issues),
            "ready": False,
            "days": days,
        }

    for item in items:
        if item["start"] < start:
            item["collision"] = True
            issues.append(
                {
                    "type": "collision",
                    "message": (
                        f"{item['name']} starts before {start_caption} at {format_minutes(start)}."
                    ),
                }
            )

    cursor = start
    lesson_no = 1

    def add_lessons_until(limit):
        nonlocal cursor, lesson_no
        while cursor < limit:
            end = cursor + lesson
            overlaps = end > limit
            blocks.append(
                _block("lesson", f"{period_label} {lesson_no}", cursor, end, collision=overlaps)
            )
            if overlaps:
                issues.append(
                    {
                        "type": "collision",
                        "message": (
                            f"{period_label} {lesson_no} ({format_minutes(cursor)}–{format_minutes(end)}) "
                            f"overlaps the next period starting at {format_minutes(limit)}."
                        ),
                    }
                )
            cursor = end
            lesson_no += 1
            if overlaps:
                break

    def fill_limit(target):
        add_lessons_until(min(target, day_end))

    for item in items:
        if item["start"] > day_end:
            item["collision"] = True
            issues.append(
                {
                    "type": "collision",
                    "message": (
                        f"{item['name']} starts after {end_caption} "
                        f"({format_minutes(day_end)})."
                    ),
                }
            )
        if cursor < item["start"]:
            fill_limit(item["start"])
        if cursor > item["start"]:
            item["collision"] = True
            if blocks:
                blocks[-1]["collision"] = True
            if not (blocks and blocks[-1].get("collision") and blocks[-1]["kind"] == "lesson"):
                issues.append(
                    {
                        "type": "collision",
                        "message": (
                            f"{item['name']} collides with the previous period "
                            f"(starts at {format_minutes(item['start'])} while the day "
                            f"is still at {format_minutes(cursor)})."
                        ),
                    }
                )
        blocks.append(
            _block(
                "activity",
                item["name"],
                item["start"],
                item["end"],
                collision=item["collision"],
            )
        )
        cursor = max(cursor, item["end"])

    if cursor < day_end:
        add_lessons_until(day_end)
    elif cursor > day_end:
        issues.append(
            {
                "type": "collision",
                "message": (
                    f"The day overruns {end_caption} by {cursor - day_end} minutes "
                    f"({format_minutes(day_end)}–{format_minutes(cursor)})."
                ),
            }
        )
        if blocks:
            blocks[-1]["collision"] = True

    return {
        "blocks": blocks,
        "issues": _unique_issues(issues),
        "ready": True,
        "days": days,
    }


def _block(kind, label, start, end, collision=False):
    return {
        "kind": kind,
        "label": label,
        "start": start,
        "end": end,
        "start_label": format_minutes(start),
        "end_label": format_minutes(end),
        "collision": collision,
    }


def _unique_issues(issues):
    seen = set()
    unique = []
    for issue in issues:
        message = issue["message"]
        if message in seen:
            continue
        seen.add(message)
        unique.append(issue)
    return unique


def build_exam_session_preview(sessions):
    """Build an exam-day session strip and flag overlapping sessions."""
    issues = []
    items = []
    for raw in sessions:
        if hasattr(raw, "name"):
            name = (raw.name or "").strip()
            start = to_minutes(raw.start_time)
            duration = int(getattr(raw, "duration_minutes", 0) or 0)
            end = start + duration if start is not None and duration > 0 else None
        else:
            name = (raw.get("name") or "").strip()
            start = raw.get("start")
            duration = int(raw.get("duration") or 0)
            end = start + duration if start is not None and duration > 0 else raw.get("end")
        if start is None or end is None or end <= start:
            continue
        items.append(
            {
                "name": name or "SESSION",
                "start": start,
                "end": end,
                "collision": False,
            }
        )

    items.sort(key=lambda item: (item["start"], item["name"]))
    for index, current in enumerate(items):
        for other in items[index + 1 :]:
            if current["start"] < other["end"] and other["start"] < current["end"]:
                current["collision"] = True
                other["collision"] = True
                issues.append(
                    {
                        "type": "collision",
                        "message": (
                            f"{current['name']} overlaps {other['name']} from "
                            f"{format_minutes(max(current['start'], other['start']))} to "
                            f"{format_minutes(min(current['end'], other['end']))}."
                        ),
                    }
                )

    blocks = [
        _block(
            "activity",
            item["name"],
            item["start"],
            item["end"],
            collision=item["collision"],
        )
        for item in items
    ]
    return {
        "blocks": blocks,
        "issues": _unique_issues(issues),
        "ready": bool(blocks),
        "days": ["Exam day"],
    }
