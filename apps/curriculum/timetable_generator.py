import math
import random
from collections import defaultdict
from datetime import timedelta

from .schedule_preview import (
    DAY_ORDER,
    EXAM_DAY_CODE,
    build_schedule_preview,
    minutes_to_time,
)

MAX_PLAN_ATTEMPTS = 400


def _periods_overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def _is_free(busy_times, weekday, start, end):
    for booked_day, booked_start, booked_end in busy_times:
        if booked_day == weekday and _periods_overlap(start, end, booked_start, booked_end):
            return False
    return True


def resolve_schedule_profile(level, kind=None):
    from .models import LearningScheduleProfile

    if kind is None:
        kind = LearningScheduleProfile.Kind.LEARNING
    profiles = [
        profile
        for profile in level.learning_schedule_profiles.all()
        if profile.kind == kind
    ]
    category = (getattr(level, "category", "") or "").strip().upper()
    if category:
        matching = [
            profile
            for profile in profiles
            if (profile.category or "").strip().upper() == category
        ]
        if matching:
            return sorted(matching, key=lambda profile: (profile.name.lower(), profile.pk or 0))[0]
    if profiles:
        return sorted(profiles, key=lambda profile: (profile.name.lower(), profile.pk or 0))[0]

    queryset = LearningScheduleProfile.objects.filter(kind=kind).prefetch_related("activities")
    if category:
        queryset = queryset.filter(category__iexact=category)
    return queryset.order_by("name", "id").first()


def resolve_elearning_schedule_profile(level):
    from .models import LearningScheduleProfile

    return resolve_schedule_profile(level, kind=LearningScheduleProfile.Kind.ELEARNING)


def lesson_slots_from_profile(profile, period_label="Lesson", start_caption="first class", end_caption="lesson end time"):
    if not profile:
        return []
    preview = build_schedule_preview(
        profile.first_class_start_time,
        profile.lesson_duration_minutes,
        profile.activities.all(),
        last_class_end=profile.last_class_end_time,
        study_days=profile.study_days,
        period_label=period_label,
        start_caption=start_caption,
        end_caption=end_caption,
    )
    if not preview["ready"]:
        return []
    study_days = [
        day
        for day in DAY_ORDER
        if day in {str(item).upper() for item in (profile.study_days or [])}
    ]
    lessons = [block for block in preview["blocks"] if block["kind"] == "lesson"]
    return [
        {
            "weekday": weekday,
            "period_name": lesson["label"],
            "start": lesson["start"],
            "end": lesson["end"],
        }
        for weekday in study_days
        for lesson in lessons
    ]


def _level_slots(level):
    profile = resolve_schedule_profile(level)
    level.schedule_profile = profile
    slots = lesson_slots_from_profile(profile)
    level.schedule_slots = slots
    return slots


def _plan_busy_key(plan):
    if plan.get("busy_key") is not None:
        return plan["busy_key"]
    academic_class = plan.get("academic_class")
    if academic_class is not None:
        return academic_class.id
    return f"level-{plan['level'].id}"


def build_class_plans(levels, allocations, teacher_ids):
    plans = []
    for level in levels:
        slots = _level_slots(level)
        subjects = list(getattr(level, "generation_subjects", []))
        for academic_class in list(getattr(level, "generation_classes", [])):
            assignments = []
            for subject in subjects:
                teacher_id = allocations.get((academic_class.id, subject.id))
                if teacher_id in teacher_ids:
                    assignments.append((subject, teacher_id))
            plans.append(
                {
                    "level": level,
                    "academic_class": academic_class,
                    "busy_key": academic_class.id,
                    "assignments": assignments,
                    "slots": slots,
                }
            )
    return plans


def build_elearning_level_plans(levels, allocations, teacher_ids):
    plans = []
    for level in levels:
        profile = resolve_elearning_schedule_profile(level)
        slots = lesson_slots_from_profile(
            profile,
            period_label="Session",
            start_caption="first session",
            end_caption="session end time",
        )
        level.schedule_profile = profile
        level.schedule_slots = slots
        subjects = list(getattr(level, "generation_subjects", []))
        assignments = []
        for subject in subjects:
            teacher_id = allocations.get((level.id, subject.id))
            if teacher_id in teacher_ids:
                assignments.append((subject, teacher_id))
        plans.append(
            {
                "level": level,
                "academic_class": None,
                "busy_key": f"elearning-level-{level.id}",
                "assignments": assignments,
                "slots": slots,
            }
        )
    return plans


def _weekday_sort_key(weekday):
    if weekday in DAY_ORDER:
        return DAY_ORDER.index(weekday)
    return len(DAY_ORDER)


def _slot_day_key(slot):
    exam_date = slot.get("exam_date")
    if exam_date:
        return exam_date.isoformat()
    return slot["weekday"]


def _placement_day_key(item):
    exam_date = item.get("exam_date")
    if exam_date:
        return exam_date.isoformat()
    return item["weekday"]


def _weekday_for_date(exam_date):
    return DAY_ORDER[exam_date.weekday()]


def _assignment_balance_key(subject, busy_key, weekday, day_counts, week_counts):
    subject_id = subject.id
    return (
        day_counts[busy_key][weekday][subject_id],
        week_counts[busy_key][subject_id],
    )


def _choose_balanced_assignment(options, busy_key, weekday, day_counts, week_counts, rng):
    best_key = None
    best = []
    for subject, teacher_id in options:
        key = _assignment_balance_key(subject, busy_key, weekday, day_counts, week_counts)
        if best_key is None or key < best_key:
            best_key = key
            best = [(subject, teacher_id)]
        elif key == best_key:
            best.append((subject, teacher_id))
    return rng.choice(best)


def _ordered_slot_keys(class_plans):
    seen = set()
    keys = []
    for plan in class_plans:
        for slot in plan["slots"]:
            key = (_slot_day_key(slot), slot["start"], slot["end"], slot["period_name"], slot["weekday"])
            if key in seen:
                continue
            seen.add(key)
            keys.append(key)
    keys.sort(
        key=lambda item: (
            item[0],
            _weekday_sort_key(item[4]),
            item[1],
            item[2],
            item[3],
        )
    )
    return keys


def _plan_once(class_plans, rng):
    teacher_busy = defaultdict(list)
    unit_busy = defaultdict(list)
    day_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    week_counts = defaultdict(lambda: defaultdict(int))
    placements = []

    for day_key, start, end, period_name, weekday in _ordered_slot_keys(class_plans):
        eligible = [
            plan
            for plan in class_plans
            if plan["assignments"]
            and any(
                _slot_day_key(slot) == day_key and slot["start"] == start and slot["end"] == end
                for slot in plan["slots"]
            )
        ]
        rng.shuffle(eligible)
        for plan in eligible:
            busy_key = _plan_busy_key(plan)
            if not _is_free(unit_busy[busy_key], day_key, start, end):
                continue

            free_options = [
                (subject, teacher_id)
                for subject, teacher_id in plan["assignments"]
                if _is_free(teacher_busy[teacher_id], day_key, start, end)
            ]
            if not free_options:
                continue

            matched_slot = next(
                slot
                for slot in plan["slots"]
                if _slot_day_key(slot) == day_key and slot["start"] == start and slot["end"] == end
            )
            subject, teacher_id = _choose_balanced_assignment(
                free_options, busy_key, day_key, day_counts, week_counts, rng
            )
            teacher_busy[teacher_id].append((day_key, start, end))
            unit_busy[busy_key].append((day_key, start, end))
            day_counts[busy_key][day_key][subject.id] += 1
            week_counts[busy_key][subject.id] += 1
            placements.append(
                {
                    "level": plan["level"],
                    "academic_class": plan.get("academic_class"),
                    "busy_key": busy_key,
                    "learning_area": subject,
                    "teacher_id": teacher_id,
                    "weekday": weekday,
                    "exam_date": matched_slot.get("exam_date"),
                    "period_name": period_name,
                    "start": start,
                    "end": end,
                }
            )
    return placements


def _plan_balance_score(placements, class_plans):
    day_counts = defaultdict(int)
    week_counts = defaultdict(int)
    repeats = 0
    for item in placements:
        busy_key = item.get("busy_key")
        if busy_key is None:
            academic_class = item.get("academic_class")
            busy_key = academic_class.id if academic_class is not None else item["level"].id
        subject_id = item["learning_area"].id
        day_key = (busy_key, _placement_day_key(item), subject_id)
        week_key = (busy_key, subject_id)
        day_counts[day_key] += 1
        week_counts[week_key] += 1
        if day_counts[day_key] > 1:
            repeats += 1
    weekly_spread = 0
    for plan in class_plans:
        busy_key = _plan_busy_key(plan)
        subject_ids = {subject.id for subject, _teacher_id in plan["assignments"]}
        if not subject_ids:
            continue
        counts = [week_counts.get((busy_key, subject_id), 0) for subject_id in subject_ids]
        weekly_spread += max(counts) - min(counts)
    return (repeats, weekly_spread)


def _minimum_same_day_repeats(class_plans):
    total = 0
    for plan in class_plans:
        subject_count = len({subject.id for subject, _teacher_id in plan["assignments"]})
        if not subject_count:
            continue
        periods_by_day = defaultdict(int)
        for slot in plan["slots"]:
            periods_by_day[_slot_day_key(slot)] += 1
        for period_count in periods_by_day.values():
            total += max(0, period_count - subject_count)
    return total


def plan_has_teacher_collision(placements):
    by_teacher = defaultdict(list)
    for item in placements:
        by_teacher[item["teacher_id"]].append(item)
    for lessons in by_teacher.values():
        for index, current in enumerate(lessons):
            for other in lessons[index + 1 :]:
                if _placement_day_key(current) != _placement_day_key(other):
                    continue
                if _periods_overlap(current["start"], current["end"], other["start"], other["end"]):
                    return True
    return False


def generate_timetable_plan(class_plans, attempts=MAX_PLAN_ATTEMPTS, seed=None):
    rng = random.Random(seed)
    total_jobs = sum(len(plan["slots"]) for plan in class_plans if plan["assignments"])
    repeat_floor = _minimum_same_day_repeats(class_plans)
    best = []
    best_quality = None
    for _ in range(max(1, attempts)):
        candidate = _plan_once(class_plans, rng)
        if plan_has_teacher_collision(candidate):
            continue
        quality = _plan_balance_score(candidate, class_plans)
        if (
            len(candidate) > len(best)
            or (len(candidate) == len(best) and (best_quality is None or quality < best_quality))
        ):
            best = candidate
            best_quality = quality
            if (
                total_jobs
                and len(best) == total_jobs
                and quality[0] <= repeat_floor
                and quality[1] <= 1
            ):
                break
    return best, total_jobs


def persist_timetable_plan(generation, placements):
    from .models import GeneratedLearningLesson

    created = []
    for item in placements:
        created.append(
            GeneratedLearningLesson(
                generation=generation,
                academic_level=item["level"],
                academic_class=item["academic_class"],
                learning_area=item["learning_area"],
                teacher_id=item["teacher_id"],
                weekday=item["weekday"],
                period_name=item["period_name"],
                start_time=minutes_to_time(item["start"]),
                end_time=minutes_to_time(item["end"]),
            )
        )
    if created:
        GeneratedLearningLesson.objects.bulk_create(created)
    return len(created)


def persist_elearning_timetable_plan(generation, placements):
    from .models import GeneratedELearningLesson

    created = []
    for item in placements:
        created.append(
            GeneratedELearningLesson(
                generation=generation,
                academic_level=item["level"],
                learning_area=item["learning_area"],
                teacher_id=item["teacher_id"],
                weekday=item["weekday"],
                period_name=item["period_name"],
                start_time=minutes_to_time(item["start"]),
                end_time=minutes_to_time(item["end"]),
            )
        )
    if created:
        GeneratedELearningLesson.objects.bulk_create(created)
    return len(created)


def resolve_exam_schedule_profile(level):
    profiles = list(level.exam_schedule_profiles.all())
    category = (getattr(level, "category", "") or "").strip().upper()
    if category:
        matching = [
            profile
            for profile in profiles
            if (profile.category or "").strip().upper() == category
        ]
        if matching:
            return sorted(matching, key=lambda profile: (profile.name.lower(), profile.pk or 0))[0]
    if profiles:
        return sorted(profiles, key=lambda profile: (profile.name.lower(), profile.pk or 0))[0]
    from .models import ExamScheduleProfile

    queryset = ExamScheduleProfile.objects.prefetch_related("activities")
    if category:
        queryset = queryset.filter(category__iexact=category)
    return queryset.order_by("name", "id").first()


def exam_slots_from_profile(profile, exam_dates=None):
    if not profile:
        return []
    preview = build_schedule_preview(
        profile.first_exam_start_time,
        profile.exam_session_duration_minutes,
        profile.activities.all(),
        last_class_end=profile.last_exam_end_time,
        period_label="Session",
        day_labels=["Assessment day"],
        start_caption="first assessment",
        end_caption="assessment end time",
    )
    if not preview["ready"]:
        return []
    sessions = [block for block in preview["blocks"] if block["kind"] == "lesson"]
    dates = list(exam_dates or [])
    if not dates:
        return [
            {
                "weekday": EXAM_DAY_CODE,
                "exam_date": None,
                "period_name": session["label"],
                "start": session["start"],
                "end": session["end"],
            }
            for session in sessions
        ]
    return [
        {
            "weekday": _weekday_for_date(exam_date),
            "exam_date": exam_date,
            "period_name": session["label"],
            "start": session["start"],
            "end": session["end"],
        }
        for exam_date in dates
        for session in sessions
    ]


def exam_days_needed(subject_count, sessions_per_day):
    if subject_count <= 0 or sessions_per_day <= 0:
        return 0
    return math.ceil(subject_count / sessions_per_day)


def exam_dates_for_subjects(start_date, subject_count, sessions_per_day, term_end):
    days_needed = exam_days_needed(subject_count, sessions_per_day)
    if days_needed <= 0:
        return []
    dates = []
    current = start_date
    while len(dates) < days_needed:
        if term_end is not None and current > term_end:
            return None
        dates.append(current)
        current += timedelta(days=1)
    return dates


def generate_exam_timetable_plan(class_plans):
    teacher_busy = defaultdict(list)
    class_busy = defaultdict(list)
    placements = []
    plans_by_level = []
    seen_levels = set()
    for plan in class_plans:
        level_id = plan["level"].id
        if level_id in seen_levels:
            continue
        seen_levels.add(level_id)
        plans_by_level.append([item for item in class_plans if item["level"].id == level_id])

    expected = 0
    for level_plans in plans_by_level:
        subjects = []
        seen_subjects = set()
        for plan in level_plans:
            for subject, _teacher_id in plan["assignments"]:
                if subject.id in seen_subjects:
                    continue
                seen_subjects.add(subject.id)
                subjects.append(subject)
        slots = list(level_plans[0]["slots"][: len(subjects)])
        expected += len(subjects) * len(level_plans)
        for index, subject in enumerate(subjects):
            slot = slots[index]
            day_key = _slot_day_key(slot)
            start = slot["start"]
            end = slot["end"]
            for plan in level_plans:
                class_id = plan["academic_class"].id
                teacher_id = next(
                    (item_id for item_subject, item_id in plan["assignments"] if item_subject.id == subject.id),
                    None,
                )
                if not _is_free(class_busy[class_id], day_key, start, end):
                    continue
                class_busy[class_id].append((day_key, start, end))
                if teacher_id is not None:
                    teacher_busy[teacher_id].append((day_key, start, end))
                placements.append(
                    {
                        "level": plan["level"],
                        "academic_class": plan["academic_class"],
                        "learning_area": subject,
                        "teacher_id": teacher_id,
                        "weekday": slot["weekday"],
                        "exam_date": slot.get("exam_date"),
                        "period_name": slot["period_name"],
                        "start": start,
                        "end": end,
                    }
                )
    return placements, expected


def build_exam_class_plans(levels, allocations, supervisor_ids, exam_dates=None, exam_dates_by_level=None):
    plans = []
    for level in levels:
        profile = resolve_exam_schedule_profile(level)
        level.schedule_profile = profile
        subjects = list(getattr(level, "generation_subjects", []))
        dates = None
        if exam_dates_by_level is not None:
            dates = exam_dates_by_level.get(level.id)
        elif exam_dates is not None:
            dates = exam_dates
        slots = exam_slots_from_profile(profile, exam_dates=dates)
        if dates:
            slots = slots[: len(subjects)]
        level.schedule_slots = slots
        for academic_class in list(getattr(level, "generation_classes", [])):
            assignments = []
            for subject in subjects:
                supervisor_id = allocations.get((academic_class.id, subject.id))
                if supervisor_id not in supervisor_ids:
                    supervisor_id = None
                assignments.append((subject, supervisor_id))
            plans.append(
                {
                    "level": level,
                    "academic_class": academic_class,
                    "assignments": assignments,
                    "slots": slots,
                }
            )
    return plans


def persist_exam_timetable_plan(generation, placements):
    from .models import GeneratedExamSitting

    created = []
    for item in placements:
        created.append(
            GeneratedExamSitting(
                generation=generation,
                academic_level=item["level"],
                academic_class=item["academic_class"],
                learning_area=item["learning_area"],
                supervisor_id=item["teacher_id"],
                weekday=item["weekday"],
                exam_date=item.get("exam_date"),
                period_name=item["period_name"],
                start_time=minutes_to_time(item["start"]),
                end_time=minutes_to_time(item["end"]),
            )
        )
    if created:
        GeneratedExamSitting.objects.bulk_create(created)
    return len(created)
