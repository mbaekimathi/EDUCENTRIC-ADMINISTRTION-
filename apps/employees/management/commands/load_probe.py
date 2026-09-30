"""Concurrent HTTP load / latency probe against a running server.

Usage:
  python manage.py load_probe
  python manage.py load_probe --base-url http://127.0.0.1:8000 --users 25 --rounds 3
"""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from django.test import Client
from django.utils import timezone

from apps.employees.models import Employee
from apps.employees.workspace import ACTIVE_WORKSPACE_ROLE_SESSION_KEY


DEFAULT_PATHS = (
    "/",
    "/workspace/teacher/",
    "/workspace/teacher/my-class/",
    "/workspace/teacher/my-class/students-class-attendance/",
    "/workspace/teacher/my-class/register-class-attendance/",
    "/workspace/teacher/my-class/students-discipline/",
    "/workspace/teacher/exam-records/",
    "/workspace/it_support/",
    "/workspace/it_support/system-performance/",
)


@dataclass
class Sample:
    path: str
    status: int
    ms: float
    bytes: int
    error: str = ""


@dataclass
class PathStats:
    path: str
    samples: list[Sample] = field(default_factory=list)

    def add(self, sample: Sample):
        self.samples.append(sample)

    @property
    def ok(self):
        return [s for s in self.samples if 200 <= s.status < 400 and not s.error]

    @property
    def errors(self):
        return [s for s in self.samples if s.status >= 500 or s.error or s.status == 0]


def _auth_cookie(user: Employee) -> str:
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    store[ACTIVE_WORKSPACE_ROLE_SESSION_KEY] = user.role
    store["edu_last_activity"] = timezone.now().isoformat()
    store.save()
    return store.session_key


def _pick_users(limit: int) -> list[Employee]:
    # Prefer class teachers first — they exercise the heaviest my-class pages.
    from apps.curriculum.models import AcademicClass

    class_teacher_ids = list(
        AcademicClass.objects.filter(
            status=AcademicClass.Status.ACTIVE,
            class_teacher_id__isnull=False,
        )
        .values_list("class_teacher_id", flat=True)
        .distinct()
    )
    teachers = list(
        Employee.objects.filter(
            pk__in=class_teacher_ids,
            is_active=True,
            approval_status=Employee.ApprovalStatus.APPROVED,
        ).order_by("id")
    )
    more_teachers = list(
        Employee.objects.filter(
            is_active=True,
            approval_status=Employee.ApprovalStatus.APPROVED,
            role=Employee.Role.TEACHER,
        )
        .exclude(pk__in=[t.pk for t in teachers])
        .order_by("id")[: max(1, limit)]
    )
    teachers.extend(more_teachers)
    it = (
        Employee.objects.filter(
            is_active=True,
            approval_status=Employee.ApprovalStatus.APPROVED,
            role=Employee.Role.IT_SUPPORT,
        )
        .order_by("id")
        .first()
    )
    users = teachers[:]
    if it and all(u.pk != it.pk for u in users):
        users.append(it)
    if not users:
        users = list(
            Employee.objects.filter(
                is_active=True,
                approval_status=Employee.ApprovalStatus.APPROVED,
            ).order_by("id")[:limit]
        )
    # Cycle if we need more virtual users than employees.
    while len(users) < limit and users:
        users.append(users[len(users) % len(teachers or users)])
    return users[:limit]


class Command(BaseCommand):
    help = "Probe page latency, concurrent capacity, and error rates."

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default="http://127.0.0.1:8000")
        parser.add_argument("--users", type=int, default=20)
        parser.add_argument("--rounds", type=int, default=2)
        parser.add_argument("--timeout", type=float, default=30.0)
        parser.add_argument(
            "--ramp",
            type=str,
            default="1,5,10,15,20,30,40",
            help="Comma-separated concurrent user counts for breakpoint ramp.",
        )
        parser.add_argument("--profile-queries", action="store_true")
        parser.add_argument("--json-out", default="")

    def handle(self, *args, **options):
        base = options["base_url"].rstrip("/")
        paths = list(DEFAULT_PATHS)
        users = _pick_users(options["users"])
        cookie_name = "edu_admin_sessionid"
        cookies = {u.pk: _auth_cookie(u) for u in {u.pk: u for u in users}.values()}

        self.stdout.write(self.style.NOTICE(f"Base URL: {base}"))
        self.stdout.write(self.style.NOTICE(f"Users prepared: {len(users)} (unique sessions: {len(cookies)})"))

        # --- Warm single-user page timings ---
        self.stdout.write("\n=== Page load timings (single user, sequential) ===")
        page_stats: dict[str, PathStats] = {p: PathStats(p) for p in paths}
        probe_user = users[0]
        session = requests.Session()
        session.cookies.set(cookie_name, cookies[probe_user.pk])
        for path in paths:
            url = f"{base}{path}"
            t0 = time.perf_counter()
            try:
                resp = session.get(url, timeout=options["timeout"], allow_redirects=True)
                ms = (time.perf_counter() - t0) * 1000
                sample = Sample(path, resp.status_code, ms, len(resp.content))
            except Exception as exc:
                ms = (time.perf_counter() - t0) * 1000
                sample = Sample(path, 0, ms, 0, error=str(exc)[:160])
            page_stats[path].add(sample)
            mark = "OK" if sample.status and sample.status < 400 else "FAIL"
            self.stdout.write(
                f"  [{mark}] {sample.status:3}  {sample.ms:7.1f} ms  {sample.bytes:7} B  {path}"
                + (f"  ({sample.error})" if sample.error else "")
            )

        # --- Concurrent ramp / breakpoint ---
        ramp = [int(x.strip()) for x in options["ramp"].split(",") if x.strip()]
        self.stdout.write("\n=== Concurrent capacity ramp ===")
        ramp_results = []
        for n in ramp:
            n = min(n, len(users))
            if n < 1:
                continue
            result = self._run_wave(
                base=base,
                paths=paths,
                users=users[:n],
                cookies=cookies,
                cookie_name=cookie_name,
                rounds=options["rounds"],
                timeout=options["timeout"],
            )
            ramp_results.append(result)
            self.stdout.write(
                f"  users={result['users']:3d}  reqs={result['requests']:4d}  "
                f"ok={result['ok_pct']:5.1f}%  err500={result['err500']:3d}  "
                f"p50={result['p50_ms']:7.1f}ms  p95={result['p95_ms']:7.1f}ms  "
                f"max={result['max_ms']:7.1f}ms  rps={result['rps']:5.1f}"
            )
            # Soft stop once error rate or latency breaks usability.
            if result["ok_pct"] < 90 or result["p95_ms"] > 8000:
                self.stdout.write(
                    self.style.WARNING(
                        f"  >> Breakpoint signal around {n} concurrent users "
                        f"(ok={result['ok_pct']:.1f}%, p95={result['p95_ms']:.0f}ms)"
                    )
                )
                break

        # --- Query profile on heaviest pages via Django test client ---
        query_profiles = []
        if options["profile_queries"]:
            self.stdout.write("\n=== Query profile (Django client, DEBUG queries) ===")
            from django.conf import settings

            if not settings.DEBUG:
                self.stdout.write(self.style.WARNING("DEBUG is False; query capture limited."))
            client = Client()
            client.force_login(probe_user)
            client.session[ACTIVE_WORKSPACE_ROLE_SESSION_KEY] = probe_user.role
            client.session.save()
            for path in paths:
                reset_queries()
                with CaptureQueriesContext(connection) as ctx:
                    t0 = time.perf_counter()
                    response = client.get(path)
                    ms = (time.perf_counter() - t0) * 1000
                profile = {
                    "path": path,
                    "status": response.status_code,
                    "ms": round(ms, 1),
                    "queries": len(ctx),
                }
                query_profiles.append(profile)
                self.stdout.write(
                    f"  {profile['status']:3}  {profile['ms']:7.1f} ms  "
                    f"queries={profile['queries']:3d}  {path}"
                )

        summary = {
            "page_timings": {
                p: {
                    "status": s.samples[0].status if s.samples else None,
                    "ms": round(s.samples[0].ms, 1) if s.samples else None,
                    "bytes": s.samples[0].bytes if s.samples else None,
                    "error": s.samples[0].error if s.samples else "",
                }
                for p, s in page_stats.items()
            },
            "ramp": ramp_results,
            "query_profiles": query_profiles,
        }
        if options["json_out"]:
            with open(options["json_out"], "w", encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2)
            self.stdout.write(self.style.SUCCESS(f"\nWrote {options['json_out']}"))

        self.stdout.write(self.style.SUCCESS("\nLoad probe complete."))

    def _run_wave(self, *, base, paths, users, cookies, cookie_name, rounds, timeout):
        # Each virtual user hits every path once per round.
        jobs = []
        for _round in range(rounds):
            for idx, user in enumerate(users):
                path = paths[idx % len(paths)]
                jobs.append((user, path))

        samples: list[Sample] = []
        t_start = time.perf_counter()

        def hit(user, path):
            url = f"{base}{path}"
            t0 = time.perf_counter()
            try:
                resp = requests.get(
                    url,
                    cookies={cookie_name: cookies[user.pk]},
                    timeout=timeout,
                    allow_redirects=True,
                )
                return Sample(path, resp.status_code, (time.perf_counter() - t0) * 1000, len(resp.content))
            except Exception as exc:
                return Sample(path, 0, (time.perf_counter() - t0) * 1000, 0, error=str(exc)[:160])

        with ThreadPoolExecutor(max_workers=len(users)) as pool:
            futures = [pool.submit(hit, u, p) for u, p in jobs]
            for fut in as_completed(futures):
                samples.append(fut.result())

        elapsed = max(time.perf_counter() - t_start, 0.001)
        latencies = [s.ms for s in samples]
        ok = [s for s in samples if 200 <= s.status < 400 and not s.error]
        err500 = [s for s in samples if s.status >= 500]
        latencies_sorted = sorted(latencies) if latencies else [0]

        def pct(p):
            if not latencies_sorted:
                return 0.0
            idx = min(len(latencies_sorted) - 1, int(round((p / 100) * (len(latencies_sorted) - 1))))
            return latencies_sorted[idx]

        return {
            "users": len(users),
            "requests": len(samples),
            "ok_pct": round(100 * len(ok) / max(len(samples), 1), 1),
            "err500": len(err500),
            "errors": len(samples) - len(ok),
            "p50_ms": round(pct(50), 1),
            "p95_ms": round(pct(95), 1),
            "max_ms": round(max(latencies) if latencies else 0, 1),
            "mean_ms": round(statistics.mean(latencies), 1) if latencies else 0,
            "rps": round(len(samples) / elapsed, 1),
            "sample_errors": [
                {"path": s.path, "status": s.status, "error": s.error}
                for s in samples
                if s.status >= 500 or s.error
            ][:8],
        }
