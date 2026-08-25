from random import Random
from datetime import date, time
from types import SimpleNamespace
from unittest import TestCase

from apps.curriculum.supervisor_allocator import shuffle_level_supervisors
from apps.curriculum.timetable_generator import (
    exam_dates_for_subjects,
    exam_slots_from_profile,
    generate_exam_timetable_plan,
    generate_timetable_plan,
    lesson_slots_from_profile,
    plan_has_teacher_collision,
)


def _plan(class_id, teacher_id, slots, subject_id=10):
    return {
        "level": SimpleNamespace(id=1),
        "academic_class": SimpleNamespace(id=class_id),
        "assignments": [(SimpleNamespace(id=subject_id), teacher_id)],
        "slots": slots,
    }


def _multi_subject_plan(class_id, slots, assignments):
    return {
        "level": SimpleNamespace(id=1),
        "academic_class": SimpleNamespace(id=class_id),
        "assignments": [
            (SimpleNamespace(id=subject_id), teacher_id) for subject_id, teacher_id in assignments
        ],
        "slots": slots,
    }


def _week_slots(days, periods):
    slots = []
    for weekday in days:
        for index in range(periods):
            start = 480 + (index * 40)
            slots.append(
                {
                    "weekday": weekday,
                    "period_name": f"Lesson {index + 1}",
                    "start": start,
                    "end": start + 40,
                }
            )
    return slots


class TimetableGeneratorTests(TestCase):
    def test_slots_follow_timetable_settings_days_duration_and_breaks(self):
        activity = SimpleNamespace(name="BREAK", start_time=time(8, 40), duration_minutes=20)
        profile = SimpleNamespace(
            first_class_start_time=time(8, 0),
            lesson_duration_minutes=40,
            last_class_end_time=time(9, 40),
            study_days=["MON", "FRI"],
            activities=SimpleNamespace(all=lambda: [activity]),
        )
        slots = lesson_slots_from_profile(profile)
        self.assertEqual({slot["weekday"] for slot in slots}, {"MON", "FRI"})
        self.assertEqual(
            {(slot["start"], slot["end"]) for slot in slots if slot["weekday"] == "MON"},
            {(480, 520), (540, 580)},
        )
        self.assertEqual(len(slots), 4)

    def test_same_teacher_cannot_take_two_classes_in_the_same_period(self):
        slot = {"weekday": "MON", "period_name": "Lesson 1", "start": 480, "end": 520}
        placements, total_slots = generate_timetable_plan(
            [_plan(1, 9, [slot]), _plan(2, 9, [slot])],
            attempts=40,
            seed=7,
        )
        self.assertEqual(total_slots, 2)
        self.assertEqual(len(placements), 1)
        self.assertFalse(plan_has_teacher_collision(placements))

    def test_different_teachers_can_share_the_same_period(self):
        slot = {"weekday": "MON", "period_name": "Lesson 1", "start": 480, "end": 520}
        placements, total_slots = generate_timetable_plan(
            [_plan(1, 9, [slot]), _plan(2, 8, [slot])],
            attempts=40,
            seed=3,
        )
        self.assertEqual(total_slots, 2)
        self.assertEqual(len(placements), 2)
        self.assertFalse(plan_has_teacher_collision(placements))

    def test_same_teacher_can_teach_consecutive_periods(self):
        slots = [
            {"weekday": "MON", "period_name": "Lesson 1", "start": 480, "end": 520},
            {"weekday": "MON", "period_name": "Lesson 2", "start": 520, "end": 560},
        ]
        placements, total_slots = generate_timetable_plan(
            [_plan(1, 9, slots)],
            attempts=20,
            seed=1,
        )
        self.assertEqual(total_slots, 2)
        self.assertEqual(len(placements), 2)
        self.assertFalse(plan_has_teacher_collision(placements))

    def test_prefers_one_subject_per_day_and_balances_weekly_hours(self):
        slots = _week_slots(["MON", "TUE"], 2)
        placements, total_slots = generate_timetable_plan(
            [_multi_subject_plan(1, slots, [(1, 11), (2, 12), (3, 13)])],
            attempts=40,
            seed=4,
        )
        self.assertEqual(total_slots, 4)
        self.assertEqual(len(placements), 4)
        by_day = {}
        by_subject = {}
        for item in placements:
            by_day.setdefault(item["weekday"], []).append(item["learning_area"].id)
            by_subject[item["learning_area"].id] = by_subject.get(item["learning_area"].id, 0) + 1
        self.assertEqual(len(set(by_day["MON"])), 2)
        self.assertEqual(len(set(by_day["TUE"])), 2)
        self.assertLessEqual(max(by_subject.values()) - min(by_subject.values()), 1)
        self.assertEqual(set(by_subject), {1, 2, 3})

    def test_spreads_repeat_lessons_evenly_when_a_day_has_more_periods_than_subjects(self):
        slots = _week_slots(["MON"], 4)
        placements, total_slots = generate_timetable_plan(
            [_multi_subject_plan(1, slots, [(1, 11), (2, 12)])],
            attempts=20,
            seed=2,
        )
        self.assertEqual(total_slots, 4)
        self.assertEqual(len(placements), 4)
        by_subject = {}
        for item in placements:
            by_subject[item["learning_area"].id] = by_subject.get(item["learning_area"].id, 0) + 1
        self.assertEqual(by_subject[1], 2)
        self.assertEqual(by_subject[2], 2)


class SupervisorAllocatorTests(TestCase):
    def test_one_supervisor_is_assigned_per_subject_for_the_level(self):
        math = SimpleNamespace(id=1)
        english = SimpleNamespace(id=2)
        ali = SimpleNamespace(id=10)
        beth = SimpleNamespace(id=11)
        assigned = shuffle_level_supervisors(
            [math, english],
            {1: {10}, 2: {11}},
            [ali, beth],
            rng=Random(3),
        )
        self.assertEqual(assigned[1], beth)
        self.assertEqual(assigned[2], ali)

    def test_class_teacher_is_skipped_when_another_teacher_is_available(self):
        math = SimpleNamespace(id=1)
        ali = SimpleNamespace(id=10)
        beth = SimpleNamespace(id=11)
        assigned = shuffle_level_supervisors(
            [math],
            {1: {10}},
            [ali, beth],
            rng=Random(1),
        )
        self.assertEqual(assigned[1], beth)


class ExamTimetableGeneratorTests(TestCase):
    def test_slots_follow_exam_profile_duration_and_breaks(self):
        activity = SimpleNamespace(name="BREAK", start_time=time(10, 0), duration_minutes=30)
        profile = SimpleNamespace(
            first_exam_start_time=time(8, 0),
            exam_session_duration_minutes=120,
            last_exam_end_time=time(12, 30),
            activities=SimpleNamespace(all=lambda: [activity]),
        )
        slots = exam_slots_from_profile(profile)
        self.assertEqual({slot["weekday"] for slot in slots}, {"EXM"})
        self.assertEqual(
            {(slot["start"], slot["end"]) for slot in slots},
            {(480, 600), (630, 750)},
        )

    def test_slots_repeat_profile_sessions_on_selected_exam_dates(self):
        profile = SimpleNamespace(
            first_exam_start_time=time(8, 0),
            exam_session_duration_minutes=120,
            last_exam_end_time=time(10, 0),
            activities=SimpleNamespace(all=lambda: []),
        )
        slots = exam_slots_from_profile(
            profile,
            exam_dates=[date(2026, 8, 19), date(2026, 8, 20)],
        )
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0]["weekday"], "WED")
        self.assertEqual(slots[0]["exam_date"], date(2026, 8, 19))
        self.assertEqual(slots[1]["weekday"], "THU")
        self.assertEqual(slots[1]["exam_date"], date(2026, 8, 20))

    def test_exam_dates_cover_each_subject_once_from_the_start_date(self):
        dates = exam_dates_for_subjects(date(2026, 8, 19), subject_count=3, sessions_per_day=2, term_end=date(2026, 11, 20))
        self.assertEqual(dates, [date(2026, 8, 19), date(2026, 8, 20)])
        self.assertIsNone(
            exam_dates_for_subjects(date(2026, 11, 19), subject_count=5, sessions_per_day=1, term_end=date(2026, 11, 20))
        )

    def test_each_subject_is_placed_in_one_session_without_repetition(self):
        profile = SimpleNamespace(
            first_exam_start_time=time(8, 0),
            exam_session_duration_minutes=120,
            last_exam_end_time=time(12, 0),
            activities=SimpleNamespace(all=lambda: []),
        )
        dates = [date(2026, 8, 19), date(2026, 8, 20)]
        slots = exam_slots_from_profile(profile, exam_dates=dates)[:3]
        math = SimpleNamespace(id=10)
        english = SimpleNamespace(id=11)
        science = SimpleNamespace(id=12)
        placements, expected = generate_exam_timetable_plan(
            [
                {
                    "level": SimpleNamespace(id=1),
                    "academic_class": SimpleNamespace(id=1),
                    "assignments": [(math, 9), (english, 9), (science, 9)],
                    "slots": slots,
                }
            ]
        )
        self.assertEqual(expected, 3)
        self.assertEqual(len(placements), 3)
        self.assertEqual({item["learning_area"].id for item in placements}, {10, 11, 12})
        self.assertEqual(len({(item["exam_date"], item["start"]) for item in placements}), 3)
