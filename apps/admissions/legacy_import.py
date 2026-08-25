import re
from datetime import date, datetime

from .models import ParentGuardian, Student


COLUMN_NAMES = (
    "id",
    "student_id",
    "full_name",
    "date_of_birth",
    "gender",
    "current_grade",
    "previous_school",
    "assessment_number",
    "address",
    "medical_info",
    "special_needs",
    "profile_image",
    "parent_info_verified",
    "parent_info_verified_at",
    "student_category",
    "sponsor_name",
    "sponsor_phone",
    "sponsor_email",
    "status",
    "created_at",
    "updated_at",
)

GRADE_STREAM_RE = re.compile(r"^(\d+)\s*([A-Za-z]+)?$")
GRADE_LABEL_RE = re.compile(r"^GRADE\s*(\d+)$", re.IGNORECASE)


def parse_legacy_student_rows(sql_text: str) -> list[dict]:
    rows = []
    pos = 0
    while True:
        insert_at = sql_text.find("INSERT INTO `students`", pos)
        if insert_at < 0:
            break
        values_at = sql_text.find("VALUES", insert_at)
        if values_at < 0:
            break
        tuples, pos = _parse_value_tuples(sql_text, values_at + 6)
        for fields in tuples:
            if len(fields) != len(COLUMN_NAMES):
                continue
            rows.append(dict(zip(COLUMN_NAMES, fields)))
    return rows


def _parse_value_tuples(text: str, start: int) -> tuple[list[list], int]:
    tuples = []
    i = start
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if text[i] == ";":
            return tuples, i + 1
        if text[i] != "(":
            return tuples, i
        i += 1
        fields = []
        current = []
        in_str = False
        while i < n:
            c = text[i]
            if in_str:
                if c == "\\" and i + 1 < n:
                    current.append(text[i + 1])
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        current.append("'")
                        i += 2
                        continue
                    in_str = False
                    i += 1
                    continue
                current.append(c)
                i += 1
                continue
            if c == "'":
                in_str = True
                i += 1
                continue
            if c == ",":
                fields.append(_token_to_value("".join(current)))
                current = []
                i += 1
                continue
            if c == ")":
                fields.append(_token_to_value("".join(current)))
                i += 1
                break
            current.append(c)
            i += 1
        tuples.append(fields)
    return tuples, i


def _token_to_value(raw: str):
    val = raw.strip()
    if not val or val.upper() == "NULL":
        return None
    return val


def split_full_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in (full_name or "").split() if part]
    if not parts:
        return "UNKNOWN", "UNKNOWN"
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def map_gender(value: str | None) -> str:
    text = (value or "").strip().upper()
    if text.startswith("F"):
        return Student.Gender.FEMALE
    if text.startswith("M"):
        return Student.Gender.MALE
    return Student.Gender.OTHER


def map_academic_level(current_grade: str | None) -> str:
    text = (current_grade or "").strip()
    if not text:
        return Student.AcademicLevel.OTHER
    label = GRADE_LABEL_RE.match(text)
    if label:
        return _grade_choice(int(label.group(1)))
    compact = text.replace(" ", "")
    stream = GRADE_STREAM_RE.match(compact)
    if stream:
        return _grade_choice(int(stream.group(1)))
    return Student.AcademicLevel.OTHER


def _grade_choice(number: int) -> str:
    key = f"GRADE_{number}"
    if key in Student.AcademicLevel.values:
        return key
    return Student.AcademicLevel.OTHER


def map_sponsorship(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in {"both", "government and self sponsored"}:
        return Student.SponsorshipCategory.BOTH
    if "government" in text:
        return Student.SponsorshipCategory.GOVERNMENT
    if "self" in text:
        return Student.SponsorshipCategory.SELF
    return Student.SponsorshipCategory.BOTH


def parse_date(value: str | None) -> date:
    text = (value or "").strip()
    if not text:
        return date(2000, 1, 1)
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def build_sponsor_details(row: dict) -> str:
    parts = [
        clean_text(row.get("sponsor_name")),
        clean_text(row.get("sponsor_phone")),
        clean_text(row.get("sponsor_email")),
    ]
    return " | ".join(part for part in parts if part)


def parent_phone_for(row: dict, used_phones: set[str]) -> str:
    raw = clean_text(row.get("sponsor_phone"))
    if re.fullmatch(r"\+?[0-9\s-]{7,24}", raw):
        return raw
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) >= 7:
        return digits[:24]
    source = re.sub(r"[^0-9]", "", clean_text(row.get("student_id"))) or str(row.get("id") or "0")
    placeholder = f"000{source.zfill(7)}"[:24]
    candidate = placeholder
    suffix = 0
    while candidate in used_phones:
        suffix += 1
        candidate = f"{placeholder[:18]}{suffix}"[:24]
    return candidate


def unique_assessment_number(row: dict, used: set[str]) -> str:
    assessment = clean_text(row.get("assessment_number")).upper()
    admission = clean_text(row.get("student_id")).upper()
    candidate = assessment or admission or f"LEGACY-{row['id']}"
    if candidate not in used:
        return candidate[:50]
    suffixed = f"{candidate}-{admission or row['id']}"[:50]
    extra = 1
    while suffixed in used:
        extra += 1
        suffixed = f"{candidate}-{extra}"[:50]
    return suffixed


def import_legacy_students(sql_text: str) -> dict:
    rows = parse_legacy_student_rows(sql_text)
    created = 0
    skipped = 0
    used_assessments = set(Student.objects.values_list("assessment_number", flat=True))
    used_admissions = {
        value for value in Student.objects.values_list("admission_number", flat=True) if value
    }
    used_phones = set(ParentGuardian.objects.values_list("phone_number", flat=True))

    for row in rows:
        admission = clean_text(row.get("student_id")).upper() or f"LEGACY-{row['id']}"
        if admission in used_admissions:
            skipped += 1
            continue

        full_name = clean_text(row.get("full_name"))
        first_name, last_name = split_full_name(full_name)
        phone = parent_phone_for(row, used_phones)
        parent_name = clean_text(row.get("sponsor_name")) or "NOT PROVIDED"
        parent_email = clean_text(row.get("sponsor_email"))
        parent, parent_created = ParentGuardian.objects.get_or_create(
            phone_number=phone,
            defaults={
                "full_name": parent_name,
                "relationship_to_student": "GUARDIAN",
                "email": parent_email,
            },
        )
        used_phones.add(phone)
        if parent_created:
            parent.is_active = False
            parent.save(update_fields=["is_active"])

        assessment = unique_assessment_number(row, used_assessments)
        used_assessments.add(assessment)
        used_admissions.add(admission)

        Student.objects.create(
            first_name=first_name,
            last_name=last_name,
            date_of_birth=parse_date(row.get("date_of_birth")),
            gender=map_gender(row.get("gender")),
            academic_level=map_academic_level(row.get("current_grade")),
            admission_number=admission,
            class_group=clean_text(row.get("current_grade")),
            assessment_number=assessment,
            previous_school=clean_text(row.get("previous_school")),
            sponsorship_category=map_sponsorship(row.get("student_category")),
            sponsor_details=build_sponsor_details(row),
            parent_guardian=parent,
            home_address=clean_text(row.get("address")),
            medical_notes=clean_text(row.get("medical_info")),
            special_needs=clean_text(row.get("special_needs")),
            emergency_contact=clean_text(row.get("sponsor_phone")) or phone,
            is_active=False,
        )
        created += 1

    return {"parsed": len(rows), "created": created, "skipped": skipped}
