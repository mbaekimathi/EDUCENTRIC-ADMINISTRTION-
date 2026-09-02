"""
Stress and load characterization for Educentric ADMINISTRATION.

Usage:
    python scripts/stress_test.py
    python scripts/stress_test.py --workers 20 --requests 100
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, reset_queries
from django.test import Client

from apps.admissions.models import Student
from apps.curriculum.models import GeneratedExamTimetable, LearningArea
from apps.employees.models import Employee
from apps.employees.views import _save_exam_record_marks

User = get_user_model()


@dataclass
class EndpointResult:
    name: str
    path: str
    times_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sizes_kb: list[float] = field(default_factory=list)
    status_codes: list[int] = field(default_factory=list)

    @property
    def count(self):
        return len(self.times_ms)

    def percentile(self, p: float) -> float:
        if not self.times_ms:
            return 0.0
        ordered = sorted(self.times_ms)
        index = min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))
        return ordered[index]

    def summary(self) -> str:
        if not self.times_ms:
            return f"{self.name}: NO SUCCESSFUL REQUESTS ({len(self.errors)} errors)"
        avg_kb = statistics.mean(self.sizes_kb) if self.sizes_kb else 0
        return (
            f"{self.name}\n"
            f"  path: {self.path}\n"
            f"  ok: {self.count}  errors: {len(self.errors)}  "
            f"status: {max(set(self.status_codes), key=self.status_codes.count)}\n"
            f"  size: {avg_kb:.0f} KB avg\n"
            f"  ms  p50={self.percentile(50):.0f}  p95={self.percentile(95):.0f}  "
            f"p99={self.percentile(99):.0f}  max={max(self.times_ms):.0f}"
        )


def _ensure_hosts():
    for host in ("testserver", "127.0.0.1", "localhost"):
        if host not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append(host)


def _login_client(role: str) -> Client | None:
    employee = (
        Employee.objects.filter(
            role=role,
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_active=True,
        )
        .order_by("id")
        .first()
    )
    if employee is None:
        return None
    client = Client()
    client.force_login(employee)
    return client


def _hit(client: Client, path: str) -> tuple[float, int, float, str | None]:
    started = time.perf_counter()
    try:
        response = client.get(path)
        elapsed_ms = (time.perf_counter() - started) * 1000
        size_kb = len(response.content) / 1024
        error = None if response.status_code < 400 else f"HTTP {response.status_code}"
        return elapsed_ms, response.status_code, size_kb, error
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, 0, 0.0, str(exc)


def run_endpoint_stress(
    name: str,
    path: str,
    client: Client,
    *,
    workers: int,
    requests: int,
) -> EndpointResult:
    result = EndpointResult(name=name, path=path)

    def worker(_index: int):
        return _hit(client, path)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, i) for i in range(requests)]
        for future in as_completed(futures):
            elapsed_ms, status, size_kb, error = future.result()
            if error:
                result.errors.append(error)
            else:
                result.times_ms.append(elapsed_ms)
                result.status_codes.append(status)
                result.sizes_kb.append(size_kb)
    return result


def profile_queries(label: str, func):
    reset_queries()
    started = time.perf_counter()
    func()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "label": label,
        "queries": len(connection.queries),
        "ms": elapsed_ms,
    }


def profile_write_load():
    generation = GeneratedExamTimetable.objects.first()
    subject = LearningArea.objects.first()
    students = list(Student.objects.all()[:40])
    if not generation or not subject or not students:
        return None
    post_data = {f"mark_{student.id}_{subject.id}": "72" for student in students}

    def save_once():
        _save_exam_record_marks(
            generation,
            students,
            [subject],
            {subject.id: 100},
            post_data,
        )

    return profile_queries("assessment mark save (40 students)", save_once)


def profile_concurrent_writes(workers: int, rounds: int):
    generation = GeneratedExamTimetable.objects.first()
    subject = LearningArea.objects.first()
    students = list(Student.objects.all()[:20])
    if not generation or not subject or not students:
        return None

    errors = []
    times_ms = []

    def save_batch(batch_index: int):
        post_data = {
            f"mark_{student.id}_{subject.id}": str(70 + (batch_index % 10))
            for student in students
        }
        started = time.perf_counter()
        try:
            _save_exam_record_marks(
                generation,
                students,
                [subject],
                {subject.id: 100},
                post_data,
            )
            return (time.perf_counter() - started) * 1000, None
        except Exception as exc:
            return (time.perf_counter() - started) * 1000, str(exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(save_batch, i) for i in range(rounds)]
        for future in as_completed(futures):
            elapsed_ms, error = future.result()
            times_ms.append(elapsed_ms)
            if error:
                errors.append(error)

    return {
        "workers": workers,
        "rounds": rounds,
        "errors": len(errors),
        "p50_ms": statistics.median(times_ms) if times_ms else 0,
        "p95_ms": sorted(times_ms)[int(0.95 * (len(times_ms) - 1))] if times_ms else 0,
        "max_ms": max(times_ms) if times_ms else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Stress test Educentric ADMINISTRATION")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent workers per endpoint")
    parser.add_argument("--requests", type=int, default=50, help="Requests per endpoint")
    args = parser.parse_args()

    _ensure_hosts()

    print("=" * 60)
    print("EDUCENTRIC STRESS TEST")
    print("=" * 60)
    print(f"Database: {settings.DATABASES['default']['ENGINE'].rsplit('.', 1)[-1]}")
    print(f"DEBUG: {settings.DEBUG}")
    print(f"Cache: {settings.CACHES['default']['BACKEND'].rsplit('.', 1)[-1]}")
    print(f"Students: {Student.objects.count()}")
    print(f"Workers: {args.workers}  Requests/endpoint: {args.requests}")
    print()

    clients = {
        "it_support": _login_client(Employee.Role.IT_SUPPORT),
        "teacher": _login_client(Employee.Role.TEACHER),
    }

    endpoints = [
        ("IT: student management (default level)", "/workspace/it_support/student-management/", "it_support"),
        ("IT: student management (GRADE_2)", "/workspace/it_support/student-management/?level=GRADE_2", "it_support"),
        ("IT: exam records", "/workspace/it_support/curriculum-management/exam-management/exam-records/", "it_support"),
        ("Teacher: dashboard", "/workspace/teacher/", "teacher"),
        ("Teacher: exam records", "/workspace/teacher/exam-records/", "teacher"),
        ("API: student search", "/workspace/students/search/?q=ANN", "teacher"),
    ]

    results: list[EndpointResult] = []
    for name, path, role_key in endpoints:
        client = clients.get(role_key)
        if client is None:
            print(f"SKIP {name}: no {role_key} user")
            continue
        print(f"Running {name}...")
        results.append(
            run_endpoint_stress(
                name,
                path,
                client,
                workers=args.workers,
                requests=args.requests,
            )
        )

    print()
    print("-" * 60)
    print("ENDPOINT RESULTS")
    print("-" * 60)
    for result in results:
        print(result.summary())
        print()

    print("-" * 60)
    print("QUERY PROFILING (single request)")
    print("-" * 60)
    profiles = []
    it_client = clients.get("it_support")
    teacher_client = clients.get("teacher")
    if it_client:
        profiles.append(
            profile_queries(
                "student management (cold)",
                lambda: it_client.get("/workspace/it_support/student-management/"),
            )
        )
        profiles.append(
            profile_queries(
                "student management (warm)",
                lambda: it_client.get("/workspace/it_support/student-management/"),
            )
        )
    if teacher_client:
        profiles.append(
            profile_queries(
                "teacher dashboard",
                lambda: teacher_client.get("/workspace/teacher/"),
            )
        )

    write_profile = profile_write_load()
    if write_profile:
        profiles.append(write_profile)

    for item in profiles:
        print(f"  {item['label']}: {item['queries']} queries, {item['ms']:.0f} ms")

    print()
    print("-" * 60)
    print("CONCURRENT WRITE TEST (assessment marks)")
    print("-" * 60)
    write_result = profile_concurrent_writes(workers=5, rounds=20)
    if write_result:
        print(
            f"  {write_result['rounds']} saves, {write_result['workers']} workers, "
            f"errors={write_result['errors']}\n"
            f"  p50={write_result['p50_ms']:.0f}ms  p95={write_result['p95_ms']:.0f}ms  "
            f"max={write_result['max_ms']:.0f}ms"
        )
    else:
        print("  SKIP: missing exam/student fixtures")

    print()
    print("-" * 60)
    print("BOTTLENECK ANALYSIS")
    print("-" * 60)
    slow = sorted(results, key=lambda r: r.percentile(95), reverse=True)
    if slow and slow[0].times_ms:
        print(f"  Slowest p95: {slow[0].name} ({slow[0].percentile(95):.0f} ms)")
    heavy = sorted(results, key=lambda r: statistics.mean(r.sizes_kb) if r.sizes_kb else 0, reverse=True)
    if heavy and heavy[0].sizes_kb:
        print(f"  Largest response: {heavy[0].name} ({statistics.mean(heavy[0].sizes_kb):.0f} KB)")
    error_total = sum(len(r.errors) for r in results)
    print(f"  Total HTTP errors: {error_total}")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
