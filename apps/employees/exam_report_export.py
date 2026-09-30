import re
from io import BytesIO
from pathlib import Path

from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def _safe_sheet_title(value, used):
    title = re.sub(r"[\\/*?:\[\]]", " ", (value or "Sheet")[:31]).strip() or "Sheet"
    base = title
    counter = 2
    while title in used:
        suffix = f" {counter}"
        title = f"{base[: 31 - len(suffix)]}{suffix}"
        counter += 1
    used.add(title)
    return title


def _safe_filename_part(value):
    cleaned = re.sub(r"[^\w\s-]+", "", (value or "").strip(), flags=re.UNICODE)
    slug = re.sub(r"[-\s]+", "-", cleaned).strip("-").casefold()
    return slug or "exam-report"


def _export_filename(report, mode, extension):
    issued_on = report.get("issued_on")
    date_part = issued_on.isoformat() if issued_on is not None else "export"
    return (
        f"{_safe_filename_part(report.get('exam_title'))}-"
        f"{_safe_filename_part(report.get('scope_label'))}-"
        f"{mode}-{date_part}.{extension}"
    )


def _format_mark_cell(cell, mode):
    if mode == "raw":
        percent = cell.get("percent")
        if percent is not None:
            return str(percent)
        raw = cell.get("raw")
        if raw in (None, ""):
            return ""
        out_of = cell.get("out_of")
        try:
            out_of_value = int(out_of)
        except (TypeError, ValueError):
            out_of_value = None
        if out_of_value not in (None, 100):
            return f"{raw}/{out_of_value}"
        return str(raw)
    percent = cell.get("percent")
    if percent is None:
        return ""
    grade = (cell.get("grade") or "").strip()
    return f"{percent} ({grade})" if grade else str(percent)


def _autosize_columns(worksheet, max_width=42):
    for column_cells in worksheet.columns:
        letter = get_column_letter(column_cells[0].column)
        width = 0
        for cell in column_cells:
            if cell.value in (None, ""):
                continue
            width = max(width, min(len(str(cell.value)), max_width))
        worksheet.column_dimensions[letter].width = max(width + 2, 10)


def _write_meta_rows(worksheet, report, sheet_title):
    worksheet.append([sheet_title])
    worksheet.append([report.get("exam_title") or ""])
    worksheet.append([report.get("scope_label") or ""])
    worksheet.append([])
    for row_index in range(1, 4):
        worksheet.cell(row=row_index, column=1).font = Font(bold=True)


def _matrix_table_data(report, sheet, mode):
    show_class = bool(report.get("show_class_column"))
    header = ["Pos", "Learner"]
    if show_class:
        header.append("Class")
    header.append("Admission no.")
    header.extend(
        (getattr(subject, "code", None) or getattr(subject, "name", "") or "")
        for subject in sheet.get("subjects") or []
    )
    if mode == "graded":
        header.extend(["Total", "Average", "Grade"])
    else:
        header.extend(["Total", "Average"])

    rows = []
    for row in sheet.get("rows") or []:
        student = row.get("student")
        position = row.get("position")
        values = [
            "" if position is None else str(position),
            student.display_name if student is not None else "",
        ]
        if show_class:
            values.append(row.get("class_label") or "")
        values.append(row.get("admission") or "")
        values.extend(_format_mark_cell(cell, mode) for cell in row.get("cells") or [])
        if row.get("is_absent"):
            values.extend(["Absent", "", ""] if mode == "graded" else ["Absent", ""])
        else:
            total = row.get("total_marks")
            mean = row.get("mean_percent")
            values.append("" if total is None else str(total))
            values.append("" if mean is None else str(mean))
            if mode == "graded":
                grade = (row.get("overall_grade") or "").strip()
                values.append(grade)
        rows.append(values)

    subject_means = sheet.get("subject_means") or []
    if subject_means:
        mean_values = ["", "Class mean"]
        if show_class:
            mean_values.append("")
        mean_values.append("")
        for mean in subject_means:
            percent = mean.get("percent_mean")
            if percent is None:
                mean_values.append("")
            elif mode == "graded":
                grade = (mean.get("grade") or "").strip()
                mean_values.append(f"{percent} ({grade})" if grade else str(percent))
            else:
                mean_values.append(str(percent))
        class_total = sheet.get("class_total_marks")
        class_mean = sheet.get("class_mean")
        mean_values.append("" if class_total is None else str(class_total))
        mean_values.append("" if class_mean is None else str(class_mean))
        if mode == "graded":
            class_grade = (sheet.get("class_mean_grade") or "").strip()
            mean_values.append(class_grade)
        rows.append(mean_values)

    title = sheet.get("exam_title") or "Exam marks"
    return title, header, rows


def _individual_table_data(report, cards, mode):
    exam_columns = []
    if cards:
        exam_columns = cards[0].get("exam_columns") or []
    header = ["Student", "Admission no.", "Class", "Subject code", "Subject name"]
    header.extend(column.get("label") or column.get("title") or "Assessment" for column in exam_columns)
    if mode == "graded" and exam_columns:
        header.append("Subject average")

    selected_class = report.get("selected_class")
    class_label = selected_class.display_label if selected_class is not None else ""

    rows = []
    for card in cards:
        student = card.get("student")
        student_name = student.display_name if student is not None else ""
        admission = (student.admission_number or "") if student is not None else ""
        student_class = class_label or ((student.class_group or "") if student is not None else "")
        for row_index, row in enumerate(card.get("rows") or []):
            subject = row.get("subject")
            subject_code = ""
            subject_name = ""
            if subject is not None:
                subject_code = getattr(subject, "code", None) or ""
                subject_name = getattr(subject, "name", None) or ""
                component_codes = getattr(subject, "component_codes", "") or ""
                if component_codes and subject_name:
                    subject_name = f"{subject_name} ({component_codes})"
            # Student identity is in the header; only show it on the first subject row.
            is_first_subject = row_index == 0
            values = [
                student_name if is_first_subject else "",
                admission if is_first_subject else "",
                student_class if is_first_subject else "",
                subject_code,
                subject_name,
            ]
            values.extend(_format_mark_cell(cell, mode) for cell in row.get("cells") or [])
            if mode == "graded" and exam_columns:
                mean = row.get("mean_percent")
                grade = (row.get("grade") or "").strip()
                if mean is None:
                    values.append("")
                elif grade:
                    values.append(f"{mean} ({grade})")
                else:
                    values.append(str(mean))
            rows.append(values)

    title = report.get("kind_label") or "Individual report"
    return title, header, rows


def _write_matrix_sheet(worksheet, report, sheet, mode):
    title, header, rows = _matrix_table_data(report, sheet, mode)
    _write_meta_rows(worksheet, report, title)
    worksheet.append(header)
    for values in rows:
        worksheet.append(values)
    _autosize_columns(worksheet)


def _write_individual_sheet(worksheet, report, cards, mode):
    title, header, rows = _individual_table_data(report, cards, mode)
    _write_meta_rows(worksheet, report, title)
    worksheet.append(header)
    for values in rows:
        worksheet.append(values)
    _autosize_columns(worksheet)


def _analytics_subject_code(subject):
    return getattr(subject, "code", None) or getattr(subject, "name", "") or "Subject"


def _format_analytics_mark(cell, mode):
    if not cell or cell.get("percent") is None:
        return "-"
    if mode == "graded" and cell.get("grade"):
        return f"{cell.get('percent')} ({cell.get('grade')})"
    return cell.get("percent")


def _analytics_table_data(report, sheet, mode):
    title = sheet.get("exam_title") or report.get("exam_title") or "Subject analytics"
    header = ["#", "Class", "Sat"]
    header.extend(_analytics_subject_code(subject) for subject in (sheet.get("subjects") or []))
    header.extend(["Total", "Mean"])
    if mode == "graded":
        header.append("Grade")
    rows = []
    for row in sheet.get("rows") or []:
        sat_label = f"{row.get('present_count') or 0}/{row.get('student_count') or 0}"
        values = [row.get("rank") or "-", row.get("class_label") or "-", sat_label]
        values.extend(_format_analytics_mark(cell, mode) for cell in (row.get("cells") or []))
        values.append(row.get("total_score") if row.get("total_score") is not None else "-")
        values.append(row.get("mean_score") if row.get("mean_score") is not None else "-")
        if mode == "graded":
            values.append(row.get("grade") or "-")
        rows.append(values)
    if sheet.get("subject_means"):
        mean_row = [
            "-",
            sheet.get("mean_label") or "Grade mean",
            f"{sheet.get('present_count') or 0}/{sheet.get('student_count') or 0}",
        ]
        mean_row.extend(
            _format_analytics_mark(
                {"percent": item.get("percent_mean"), "grade": item.get("grade")},
                mode,
            )
            for item in sheet.get("subject_means") or []
        )
        mean_row.append(sheet.get("overall_total") if sheet.get("overall_total") is not None else "-")
        mean_row.append(sheet.get("overall_mean") if sheet.get("overall_mean") is not None else "-")
        if mode == "graded":
            mean_row.append(sheet.get("overall_grade") or "-")
        rows.append(mean_row)
    return title, header, rows


def _write_analytics_sheet(worksheet, report, sheet, mode):
    title, header, rows = _analytics_table_data(report, sheet, mode)
    _write_meta_rows(worksheet, report, title)
    worksheet.append(header)
    for values in rows:
        worksheet.append(values)
    _autosize_columns(worksheet)


def build_exam_report_excel(report, *, mode="raw"):
    if mode not in {"raw", "graded"}:
        mode = "raw"
    workbook = Workbook()
    used_titles = set()
    if report.get("is_matrix"):
        workbook.remove(workbook.active)
        for sheet in report.get("matrix_sheets") or []:
            title = _safe_sheet_title(sheet.get("exam_title"), used_titles)
            worksheet = workbook.create_sheet(title=title)
            _write_matrix_sheet(worksheet, report, sheet, mode)
        if not workbook.sheetnames:
            worksheet = workbook.create_sheet(title="Report")
            _write_matrix_sheet(worksheet, report, {}, mode)
    elif report.get("is_analytics"):
        workbook.remove(workbook.active)
        for sheet in report.get("analytics_sheets") or []:
            title = _safe_sheet_title(
                sheet.get("section_title") or sheet.get("exam_title") or "Analytics",
                used_titles,
            )
            worksheet = workbook.create_sheet(title=title)
            _write_analytics_sheet(worksheet, report, sheet, mode)
        if not workbook.sheetnames:
            worksheet = workbook.create_sheet(title="Analytics")
            _write_analytics_sheet(worksheet, report, {}, mode)
    else:
        worksheet = workbook.active
        worksheet.title = _safe_sheet_title("Individual report", used_titles)
        _write_individual_sheet(worksheet, report, report.get("report_cards") or [], mode)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), _export_filename(report, mode, "xlsx")


# --- Print-matched PDF export --------------------------------------------------
# Colors / layout mirror static/css/exam-report-print.css and @media print rules.

_PDF_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_PDF_NAVY = (16, 35, 63)  # #10233f
_PDF_INK = (16, 35, 63)
_PDF_HEAD_TEXT = (30, 41, 59)  # #1e293b
_PDF_MUTED = (115, 132, 158)  # #73849e
_PDF_META = (51, 65, 85)  # #334155
_PDF_LINE = (213, 222, 236)  # #d5deec
_PDF_BORDER = (100, 116, 139)  # #64748b — print cell borders
_PDF_SOFT = (248, 251, 255)  # #f8fbff
_PDF_HEAD = (232, 238, 248)  # #e8eef8 light blue header
_PDF_ALT = (248, 250, 252)  # #f8fafc
_PDF_MEAN = (226, 234, 247)  # #e2eaf7
_PDF_SUMMARY = (238, 243, 251)  # #eef3fb
_PDF_GRADE = (228, 236, 255)  # #e4ecff
_PDF_GRADE_HEAD = (219, 230, 255)  # #dbe6ff
_PDF_BLUE = (27, 79, 214)  # #1b4fd6 — exam report / print theme
_PDF_WHITE = (255, 255, 255)
_PDF_EMPTY = (148, 163, 184)  # #94a3b8
_PDF_SUMMARY_EDGE = (51, 65, 85)  # #334155 inset for avg/total


def _resolve_pdf_fonts():
    candidates = [
        (_PDF_FONT_DIR / "DejaVuSans.ttf", _PDF_FONT_DIR / "DejaVuSans-Bold.ttf"),
        (Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")),
        (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\segoeuib.ttf")),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            return str(regular), str(bold)
    return None, None


def _pdf_text(value):
    return "" if value is None else str(value)


def _pdf_dash(value):
    text = _pdf_text(value).strip()
    return text if text else "-"


def _resolve_logo_path(profile):
    """Return an on-disk logo path if the school has an uploaded logo file."""
    logo_field = getattr(profile, "school_logo", None)
    if logo_field is None:
        return None
    name = (getattr(logo_field, "name", None) or "").strip()
    has_logo = getattr(profile, "has_logo_file", None)
    if has_logo is None:
        has_logo = bool(name)
    if not has_logo or not name:
        return None
    try:
        path = Path(logo_field.path)
    except (OSError, ValueError, AttributeError):
        return None
    if not path.is_file():
        return None
    return str(path)


def _school_brand(report):
    profile = report.get("school_profile")
    if profile is None:
        return {
            "name": "Edu-Centric School",
            "motto": "",
            "contact": "",
            "logo_path": None,
            "initial": "E",
            # Exam/print reports always use the blue report theme.
            "primary": _PDF_BLUE,
        }
    phone = " ".join(str(getattr(profile, "main_phone", "") or "").split())
    email = " ".join(str(getattr(profile, "general_email", "") or "").split())
    # Letterhead contact matches print: phone · email (address stays off the header).
    contact = " · ".join(part for part in (phone, email) if part)
    name = (
        getattr(profile, "brand_official_name", None)
        or getattr(profile, "official_name", None)
        or getattr(profile, "display_name", None)
        or "School"
    )
    initials = getattr(profile, "brand_initials", None)
    if not initials:
        initials = (getattr(profile, "display_name", None) or name or "E")[:1].upper()
    return {
        "name": name,
        "motto": (getattr(profile, "motto", None) or "").strip(),
        "contact": contact,
        "logo_path": _resolve_logo_path(profile),
        "initial": initials[:2] if initials else "E",
        # Match exam-report-print.css (#1b4fd6), not school sign-in primary_color.
        "primary": _PDF_BLUE,
    }


def _format_mark_display(cell, mode):
    if mode == "raw":
        percent = cell.get("percent")
        if percent is not None:
            return str(percent)
        raw = cell.get("raw")
        out_of = cell.get("out_of")
        if raw in (None, ""):
            return "-"
        if out_of not in (None, "", 100):
            return f"{raw}/{out_of}"
        return str(raw)
    percent = cell.get("percent")
    if percent is None:
        return "-"
    grade = (cell.get("grade") or "").strip()
    return f"{percent} ({grade})" if grade else str(percent)


def _fit(pdf, text, width, family, style, size):
    content = _pdf_text(text)
    pdf.set_font(family, style, size)
    pad = 1.6
    if not content or pdf.get_string_width(content) <= width - pad:
        return content
    ellipsis = ".."
    while content and pdf.get_string_width(content + ellipsis) > width - pad:
        content = content[:-1]
    return f"{content}{ellipsis}" if content else ellipsis


_MARK_GRADE_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")


def _split_mark_grade(value):
    """Split '88 (A)' into mark + grade for blue/black dual-color cells."""
    text = _pdf_text(value)
    match = _MARK_GRADE_RE.match(text)
    if not match:
        return text, ""
    return match.group(1).strip(), match.group(2).strip()


def _matrix_fixed_widths(header, usable_width):
    """Allocate fixed mm widths so Class / Grade / # never collapse."""
    fixed_map = {
        "pos": 7.0,
        "#": 7.0,
        "learner": 48,
        "class": 10,
        "admission no.": 13,
        "total": 10.5,
        "average": 10.5,
        "avg": 10.5,
        "grade": 9,
    }
    widths = []
    flex_indexes = []
    used = 0.0
    for index, heading in enumerate(header):
        key = str(heading or "").casefold()
        if key in fixed_map:
            width = fixed_map[key]
            widths.append(width)
            used += width
        else:
            widths.append(0)
            flex_indexes.append(index)
    remaining = max(usable_width - used, 8 * max(len(flex_indexes), 1))
    flex = remaining / max(len(flex_indexes), 1)
    for index in flex_indexes:
        widths[index] = flex
    # Normalize tiny float drift.
    scale = usable_width / sum(widths)
    return [width * scale for width in widths]


class PrintStyleExamPDF(FPDF):
    """PDF layout aligned with the browser print report design."""

    def __init__(self, report, mode, *, landscape=False):
        super().__init__(orientation="L" if landscape else "P", unit="mm", format="A4")
        self.report = report
        self.mode = mode
        self.landscape = landscape
        self.brand = _school_brand(report)
        self.primary = self.brand["primary"]
        self.font_family = "Helvetica"
        self._active_sheet = None
        self._active_card = None
        self.set_auto_page_break(auto=False, margin=10)
        self.set_margins(6, 6, 6)
        regular, bold = _resolve_pdf_fonts()
        if regular and bold:
            self.add_font("EduReport", "", regular)
            self.add_font("EduReport", "B", bold)
            self.font_family = "EduReport"

    def footer(self):
        # Quiet footer like a printed page (no branded fill bar).
        self.set_draw_color(*_PDF_LINE)
        self.set_line_width(0.25)
        self.line(self.l_margin, self.h - 8, self.w - self.r_margin, self.h - 8)
        self.set_y(-6.5)
        self.set_font(self.font_family, "B", 6.2)
        self.set_text_color(*_PDF_MUTED)
        issued = self.report.get("issued_on")
        left = "  ·  ".join(
            part
            for part in (
                self.brand["name"],
                "With grades" if self.mode == "graded" else "Raw marks",
                issued.isoformat() if issued is not None else "",
            )
            if part
        )
        self.set_x(self.l_margin)
        self.cell(self.epw * 0.72, 4, _fit(self, left, self.epw * 0.72, self.font_family, "B", 6.2), align="L")
        self.cell(self.epw * 0.28, 4, f"Page {self.page_no()}", align="R")

    def _draw_logo_or_mark(self, x, y, size):
        if self.brand["logo_path"]:
            try:
                # Fit inside a square box while keeping aspect ratio.
                self.image(self.brand["logo_path"], x=x, y=y, h=size)
                return
            except Exception:
                try:
                    self.image(self.brand["logo_path"], x=x, y=y, w=size, h=size)
                    return
                except Exception:
                    pass
        # Print-style monogram badge when no logo is available.
        self.set_fill_color(*_PDF_BLUE)
        self.set_draw_color(*_PDF_LINE)
        self.set_line_width(0.25)
        self.rect(x, y, size, size, "DF")
        self.set_xy(x, y + size * 0.28)
        self.set_font(self.font_family, "B", max(size * 0.38, 7))
        self.set_text_color(*_PDF_WHITE)
        self.cell(size, size * 0.42, self.brand["initial"], align="C")

    def _matrix_meta_line(self, sheet):
        """Build 'YEAR - TERM - EXAM · SCOPE' like the print letterhead."""
        year = self.report.get("academic_year")
        term = self.report.get("academic_term")
        year_name = (getattr(year, "name", None) or "").strip() if year is not None else ""
        term_name = (getattr(term, "name", None) or "").strip() if term is not None else ""
        exam_name = (
            sheet.get("exam_title")
            or self.report.get("exam_title")
            or sheet.get("section_title")
            or ""
        ).strip()
        selected_class = self.report.get("selected_class")
        scope = (sheet.get("scope_label") or self.report.get("scope_label") or "").strip()
        if not scope and selected_class is not None:
            scope = (getattr(selected_class, "display_label", None) or str(selected_class)).strip()
        if not scope:
            level = self.report.get("level")
            level_name = (getattr(level, "name", None) or sheet.get("level_name") or "").strip()
            if level_name:
                scope = f"{level_name} · whole grade"

        # Avoid duplicating year/term if they are already inside the exam title.
        title_fold = exam_name.casefold()
        lead = []
        if year_name and year_name.casefold() not in title_fold:
            lead.append(year_name)
        if term_name and term_name.casefold() not in title_fold:
            lead.append(term_name)
        if exam_name:
            lead.append(exam_name)
        left = " - ".join(lead)
        if left and scope:
            return f"{left} · {scope}"
        return left or scope

    def draw_matrix_letterhead(self, sheet, *, compact=False, kicker=""):
        """Standard letterhead: logo left, page-centred identity, meta, blue rule."""
        self._active_sheet = sheet
        top = self.get_y()
        logo = 14 if compact else 18
        # Identity block (centred on full page width — logo sits beside, not squeezing text).
        name_size = 11 if compact else 13
        contact_size = 7.0 if compact else 7.8
        meta_size = 7.4 if compact else 8.4
        name_h = 5.0 if compact else 5.8
        contact_h = 3.4 if compact else 3.8
        kicker_h = 2.8 if kicker else 0
        has_contact = bool(self.brand["contact"]) and not compact

        identity_h = kicker_h + name_h + (contact_h if has_contact else 0)
        logo_y = top + max((identity_h - logo) / 2.0, 0)
        self._draw_logo_or_mark(self.l_margin, logo_y, logo)

        text_top = top + max((logo - identity_h) / 2.0, 0.15)
        self.set_xy(self.l_margin, text_top)
        if kicker:
            self.set_font(self.font_family, "B", 6.0)
            self.set_text_color(*_PDF_BLUE)
            self.cell(self.epw, kicker_h, kicker.upper(), align="C", new_x="LMARGIN", new_y="NEXT")

        self.set_x(self.l_margin)
        self.set_font(self.font_family, "B", name_size)
        self.set_text_color(*_PDF_BLUE)
        self.cell(
            self.epw,
            name_h,
            _fit(self, self.brand["name"].upper(), self.epw - logo - 4, self.font_family, "B", name_size),
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )

        if has_contact:
            self.set_x(self.l_margin)
            self.set_font(self.font_family, "B", contact_size)
            self.set_text_color(*_PDF_META)
            self.cell(
                self.epw,
                contact_h,
                _fit(self, self.brand["contact"], self.epw - 8, self.font_family, "B", contact_size),
                align="C",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        # Thin grey rule sits just under the logo / identity block.
        self.set_y(max(self.get_y(), top + logo) + (1.0 if compact else 1.35))
        self.set_draw_color(*_PDF_LINE)
        self.set_line_width(0.28)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5 if compact else 1.85)

        meta = self._matrix_meta_line(sheet)
        if meta:
            self.set_font(self.font_family, "B", meta_size)
            self.set_text_color(*_PDF_BLUE)
            self.cell(
                self.epw,
                3.8 if compact else 4.2,
                _fit(self, meta, self.epw - 4, self.font_family, "B", meta_size),
                align="C",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            self.ln(1.15 if compact else 1.45)

        self.set_draw_color(*_PDF_BLUE)
        self.set_line_width(0.9 if compact else 1.1)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.8 if compact else 2.2)

    def draw_card_letterhead(self, card, *, compact=False):
        self._active_card = card
        top = self.get_y()
        usable = self.epw
        left_w = usable * 0.58
        right_w = usable - left_w - 3
        logo = 14 if compact else 16

        self._draw_logo_or_mark(self.l_margin, top, logo)
        tx = self.l_margin + logo + 2.8
        tw = left_w - logo - 2.8
        self.set_xy(tx, top)
        self.set_font(self.font_family, "B", 5.8)
        self.set_text_color(*_PDF_MUTED)
        self.cell(tw, 3.0, "STUDENT PROGRESS REPORT", new_x="LMARGIN", new_y="NEXT")
        self.set_x(tx)
        self.set_font(self.font_family, "B", 10 if compact else 11)
        self.set_text_color(*_PDF_NAVY)
        self.cell(
            tw,
            4.4,
            _fit(self, self.brand["name"].upper(), tw, self.font_family, "B", 10 if compact else 11),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        if self.brand["motto"] and not compact:
            self.set_x(tx)
            self.set_font(self.font_family, "B", 6.8)
            self.set_text_color(*_PDF_META)
            self.cell(
                tw,
                3.2,
                _fit(self, f'"{self.brand["motto"]}"', tw, self.font_family, "B", 6.8),
                new_x="LMARGIN",
                new_y="NEXT",
            )
        if self.brand["contact"] and not compact:
            self.set_x(tx)
            self.set_font(self.font_family, "B", 6.2)
            self.set_text_color(*_PDF_MUTED)
            self.cell(
                tw,
                3.0,
                _fit(self, self.brand["contact"], tw, self.font_family, "B", 6.2),
                new_x="LMARGIN",
                new_y="NEXT",
            )
        year = self.report.get("academic_year")
        exam_bits = []
        if year is not None:
            exam_bits.append(getattr(year, "name", "") or "")
        if card.get("exam_title"):
            exam_bits.append(card.get("exam_title"))
        term = card.get("academic_term")
        if term is not None and getattr(term, "name", None):
            exam_bits.append(term.name)
        if exam_bits:
            self.set_x(tx)
            self.set_font(self.font_family, "B", 6.5)
            self.set_text_color(*_PDF_INK)
            self.cell(
                tw,
                3.1,
                _fit(self, " · ".join(exam_bits), tw, self.font_family, "B", 6.5),
                new_x="LMARGIN",
                new_y="NEXT",
            )
        left_bottom = max(self.get_y(), top + logo)

        student = card.get("student")
        rx = self.l_margin + left_w + 3
        self.set_xy(rx, top)
        self.set_font(self.font_family, "B", 5.8)
        self.set_text_color(*_PDF_MUTED)
        self.cell(right_w, 3.0, "LEARNER", new_x="LMARGIN", new_y="NEXT")
        self.set_x(rx)
        self.set_font(self.font_family, "B", 10)
        self.set_text_color(*_PDF_NAVY)
        name = student.display_name.upper() if student is not None else "LEARNER"
        self.cell(
            right_w,
            4.4,
            _fit(self, name, right_w, self.font_family, "B", 10),
            new_x="LMARGIN",
            new_y="NEXT",
        )

        selected_class = self.report.get("selected_class")
        class_label = (
            selected_class.display_label
            if selected_class is not None
            else ((student.class_group or "") if student is not None else "")
        )
        level = self.report.get("level")
        facts = [
            ("Admission", (student.admission_number if student is not None else "") or "-"),
            ("Assessment", (getattr(student, "assessment_number", None) if student is not None else None) or "-"),
            ("Class", class_label or "-"),
        ]
        if level is not None:
            facts.append(("Level", level.name))
        for label, value in facts:
            self.set_x(rx)
            self.set_font(self.font_family, "B", 5.5)
            self.set_text_color(*_PDF_MUTED)
            self.cell(right_w * 0.38, 3.2, label.upper())
            self.set_font(self.font_family, "B", 6.6)
            self.set_text_color(*_PDF_INK)
            self.cell(
                right_w * 0.62,
                3.2,
                _fit(self, value, right_w * 0.62, self.font_family, "B", 6.6),
                new_x="LMARGIN",
                new_y="NEXT",
            )

        bottom = max(left_bottom, self.get_y()) + 1.4
        self.set_y(bottom)
        self.set_draw_color(*self.primary)
        self.set_line_width(0.55)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2.4)

    def draw_summary(self, card):
        items = []
        if self.mode == "graded":
            items.append(("Overall grade", card.get("overall_grade") or "-"))
        if card.get("is_absent"):
            mean_label = "Absent"
        elif card.get("mean_percent") is not None:
            mean_label = f"{card.get('mean_percent')}%"
        else:
            mean_label = "-"
        items.append(("Mean score", mean_label))
        items.append(("Subjects assessed", str(card.get("subjects_sat") or 0)))
        remark = card.get("overall_meaning") or card.get("overall_mark_level") or "-"
        items.append(("Performance remark", remark))

        gap = 1.4
        top_count = 3 if self.mode == "graded" else 2
        top_items = items[:top_count]
        remark_item = items[-1]
        box_w = (self.epw - gap * (top_count - 1)) / top_count
        y = self.get_y()
        h = 10.5
        for index, (label, value) in enumerate(top_items):
            x = self.l_margin + index * (box_w + gap)
            fill = (233, 240, 255) if label == "Overall grade" else _PDF_SOFT
            self.set_fill_color(*fill)
            self.set_draw_color(200, 210, 228)
            self.set_line_width(0.25)
            self.rect(x, y, box_w, h, "DF")
            self.set_xy(x + 2.0, y + 1.3)
            self.set_font(self.font_family, "B", 5.8)
            self.set_text_color(*_PDF_MUTED)
            self.cell(box_w - 3.5, 2.8, label.upper())
            self.set_xy(x + 2.0, y + 4.6)
            self.set_font(self.font_family, "B", 10)
            self.set_text_color(*_PDF_NAVY)
            self.cell(box_w - 3.5, 4.4, _fit(self, value, box_w - 3.5, self.font_family, "B", 10))
        self.set_y(y + h + gap)
        y = self.get_y()
        self.set_fill_color(*_PDF_SOFT)
        self.set_draw_color(200, 210, 228)
        self.rect(self.l_margin, y, self.epw, 9.2, "DF")
        self.set_xy(self.l_margin + 2.0, y + 1.1)
        self.set_font(self.font_family, "B", 5.8)
        self.set_text_color(*_PDF_MUTED)
        self.cell(self.epw - 4, 2.8, remark_item[0].upper())
        self.set_xy(self.l_margin + 2.0, y + 4.2)
        self.set_font(self.font_family, "B", 8.2)
        self.set_text_color(*_PDF_INK)
        self.cell(self.epw - 4, 3.8, _fit(self, remark_item[1], self.epw - 4, self.font_family, "B", 8.2))
        self.set_y(y + 9.2 + 2.6)

    def _paint_header_row(self, widths, headers, row_h, font_size):
        """Light header row matching print: #e8eef8, dark uppercase labels."""
        x = self.l_margin
        y = self.get_y()
        self.set_line_width(0.28)
        for width, heading in zip(widths, headers):
            key = str(heading or "").casefold()
            is_grade = key in {"grade", "total"}
            fill = _PDF_GRADE_HEAD if is_grade else _PDF_HEAD
            text = self.primary if is_grade else _PDF_HEAD_TEXT
            self.set_fill_color(*fill)
            self.set_draw_color(*_PDF_BORDER)
            self.set_text_color(*text)
            self.set_font(self.font_family, "B", max(font_size - 0.6, 4.5))
            label = _fit(
                self,
                _pdf_text(heading).upper(),
                width,
                self.font_family,
                "B",
                max(font_size - 0.6, 4.5),
            )
            self.set_xy(x, y)
            self.cell(width, row_h, label, border=1, align="C", fill=True)
            x += width
        # Stronger bottom edge under header (print: 1pt #1e293b)
        self.set_draw_color(*_PDF_HEAD_TEXT)
        self.set_line_width(0.45)
        self.line(self.l_margin, y + row_h, self.w - self.r_margin, y + row_h)
        self.set_y(y + row_h)

    def _paint_grid_cell(self, x, y, width, row_h, value, *, font_size, fill, align="C", text_color=None):
        self.set_fill_color(*fill)
        self.set_draw_color(*_PDF_BORDER)
        self.set_line_width(0.28)
        self.set_text_color(*(text_color or _PDF_INK))
        self.set_font(self.font_family, "B", font_size)
        label = _fit(self, value, width, self.font_family, "B", font_size)
        self.set_xy(x, y)
        self.cell(width, row_h, label, border=1, align=align, fill=True)

    def _paint_mark_grade_cell(self, x, y, width, row_h, value, *, font_size, fill, align="C"):
        """Paint a cell with black mark and blue grade side by side when graded."""
        mark, grade = _split_mark_grade(value)
        self.set_fill_color(*fill)
        self.set_draw_color(*_PDF_BORDER)
        self.set_line_width(0.28)
        self.set_xy(x, y)
        self.cell(width, row_h, "", border=1, fill=True)

        display = mark or value
        if not grade or self.mode != "graded":
            is_empty = _pdf_text(display).strip() in {"", "-"}
            self.set_text_color(*(_PDF_EMPTY if is_empty else _PDF_INK))
            self.set_font(self.font_family, "B", font_size)
            label = _fit(self, display, width, self.font_family, "B", font_size)
            self.set_xy(x, y)
            self.cell(width, row_h, label, border=0, align=align)
            return

        # Small breathing room between mark and grade (mm).
        gap = 1.35
        grade_size = max(font_size - 1.2, 4.0)
        self.set_font(self.font_family, "B", font_size)
        mark_w = self.get_string_width(mark) if mark else 0
        self.set_font(self.font_family, "B", grade_size)
        grade_w = self.get_string_width(grade)
        total_w = mark_w + (gap if mark else 0) + grade_w
        pad = 1.0
        if total_w > width - pad:
            self.set_font(self.font_family, "B", font_size)
            available = max(width - pad - grade_w - gap, 2.0)
            mark = _fit(self, mark, available + pad, self.font_family, "B", font_size)
            mark_w = self.get_string_width(mark) if mark else 0
            total_w = mark_w + (gap if mark else 0) + grade_w

        if align == "L":
            cursor = x + 0.5
        else:
            cursor = x + max((width - total_w) / 2, 0.3)

        if mark:
            self.set_xy(cursor, y)
            self.set_font(self.font_family, "B", font_size)
            self.set_text_color(*_PDF_INK)
            self.cell(mark_w, row_h, mark, border=0, align="L")
            cursor += mark_w + gap

        self.set_xy(cursor, y)
        self.set_font(self.font_family, "B", grade_size)
        self.set_text_color(*self.primary)
        self.cell(grade_w, row_h, grade, border=0, align="L")
        self.set_text_color(*_PDF_INK)

    def draw_results_table(self, card):
        self.set_font(self.font_family, "B", 5.8)
        self.set_text_color(*_PDF_MUTED)
        self.cell(self.epw, 3.2, "ASSESSMENT RESULTS", new_x="LMARGIN", new_y="NEXT")
        self.ln(0.5)

        is_multi = bool(card.get("is_multi_exam"))
        exam_columns = card.get("exam_columns") or []
        if is_multi:
            headers = ["Code"]
            headers.extend(col.get("label") or col.get("title") or "Exam" for col in exam_columns)
            if self.mode == "graded":
                headers.extend(["Avg", "Remark"])
            else:
                headers.append("Remark")
        else:
            headers = ["Code", "Score", "Mark", "Remark"]

        rows = []
        for row in card.get("rows") or []:
            subject = row.get("subject")
            code = ""
            if subject is not None:
                code = getattr(subject, "code", None) or getattr(subject, "name", "") or ""
            remark = row.get("meaning") or row.get("mark_level") or "-"
            if is_multi:
                values = [code]
                for cell in row.get("cells") or []:
                    values.append(_format_mark_display(cell, self.mode))
                if self.mode == "graded":
                    mean = row.get("mean_percent")
                    grade = (row.get("grade") or "").strip()
                    if mean is None:
                        values.append("-")
                    elif grade:
                        values.append(f"{mean} ({grade})")
                    else:
                        values.append(str(mean))
                values.append(remark)
            else:
                raw = row.get("raw")
                out_of = row.get("out_of")
                score = f"{raw}/{out_of}" if raw is not None and out_of else "-"
                if self.mode == "raw":
                    mark = str(row.get("percent")) if row.get("percent") is not None else "-"
                else:
                    percent = row.get("percent")
                    grade = (row.get("grade") or "").strip()
                    if percent is None:
                        mark = "-"
                    elif grade:
                        mark = f"{percent} ({grade})"
                    else:
                        mark = str(percent)
                values = [code, score, mark, remark]
            rows.append(values)

        col_count = len(headers)
        font_size = 7.0 if col_count <= 6 else (6.2 if col_count <= 10 else 5.4)
        row_h = 5.6 if font_size >= 6.8 else 5.0
        prefer = {0: 1.15, col_count - 1: 2.1}
        weights = []
        for i, heading in enumerate(headers):
            longest = len(str(heading))
            for row in rows[:30]:
                if i < len(row):
                    longest = max(longest, len(str(row[i])))
            weights.append(max(longest, 3) * prefer.get(i, 1.0))
        total = sum(weights) or 1
        widths = [self.epw * (w / total) for w in weights]

        self._paint_header_row(widths, headers, row_h, font_size)
        mark_cols = set()
        if is_multi:
            for i in range(1, 1 + len(exam_columns)):
                mark_cols.add(i)
            if self.mode == "graded":
                mark_cols.add(col_count - 2)
        else:
            mark_cols.add(2)

        for index, values in enumerate(rows):
            if self.get_y() + row_h > self.h - self.b_margin - 26:
                self.add_page()
                self.draw_card_letterhead(card, compact=True)
                self.set_font(self.font_family, "B", 5.8)
                self.set_text_color(*_PDF_MUTED)
                self.cell(self.epw, 3.2, "ASSESSMENT RESULTS (CONTINUED)", new_x="LMARGIN", new_y="NEXT")
                self.ln(0.5)
                self._paint_header_row(widths, headers, row_h, font_size)
            x = self.l_margin
            y = self.get_y()
            fill = _PDF_ALT if index % 2 else _PDF_WHITE
            for col_i, (width, value) in enumerate(zip(widths, values)):
                align = "L" if col_i in {0, col_count - 1} else "C"
                if col_i in mark_cols and self.mode == "graded":
                    self._paint_mark_grade_cell(
                        x, y, width, row_h, value, font_size=font_size, fill=fill, align=align
                    )
                else:
                    is_empty = _pdf_text(value).strip() in {"", "-"}
                    self._paint_grid_cell(
                        x,
                        y,
                        width,
                        row_h,
                        value,
                        font_size=font_size,
                        fill=fill,
                        align=align,
                        text_color=_PDF_EMPTY if is_empty else _PDF_INK,
                    )
                x += width
            self.set_y(y + row_h)

        if card.get("mean_percent") is not None:
            x = self.l_margin
            y = self.get_y()
            mean_values = ["Assessment mean"] + [""] * (col_count - 1)
            if is_multi:
                if self.mode == "graded":
                    grade = (card.get("overall_grade") or "").strip()
                    mean_values[-2] = (
                        f"{card.get('mean_percent')} ({grade})" if grade else str(card.get("mean_percent"))
                    )
                    mean_values[-1] = card.get("overall_meaning") or card.get("overall_mark_level") or "-"
                else:
                    mean_values[-1] = card.get("overall_meaning") or card.get("overall_mark_level") or "-"
            else:
                mean_values[1] = "-"
                if self.mode == "graded":
                    grade = (card.get("overall_grade") or "").strip()
                    mean_values[2] = (
                        f"{card.get('mean_percent')} ({grade})" if grade else str(card.get("mean_percent"))
                    )
                else:
                    mean_values[2] = str(card.get("mean_percent"))
                mean_values[3] = card.get("overall_meaning") or card.get("overall_mark_level") or "-"
            for col_i, (width, value) in enumerate(zip(widths, mean_values)):
                if col_i in mark_cols and self.mode == "graded" and value:
                    self._paint_mark_grade_cell(
                        x, y, width, row_h, value, font_size=font_size, fill=_PDF_MEAN, align="C"
                    )
                else:
                    self._paint_grid_cell(
                        x,
                        y,
                        width,
                        row_h,
                        value,
                        font_size=font_size,
                        fill=_PDF_MEAN,
                        align="C",
                        text_color=_PDF_NAVY,
                    )
                x += width
            # Mean row top emphasis
            self.set_draw_color(*_PDF_SUMMARY_EDGE)
            self.set_line_width(0.45)
            self.line(self.l_margin, y, self.w - self.r_margin, y)
            self.set_y(y + row_h)
        self.ln(3.5)

    def draw_signoff(self):
        if self.get_y() + 26 > self.h - self.b_margin:
            self.add_page()
            if self._active_card is not None:
                self.draw_card_letterhead(self._active_card, compact=True)
        self.set_draw_color(*_PDF_LINE)
        self.set_line_width(0.25)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3.0)
        labels = [
            ("Class teacher", self.report.get("class_teacher_name") or "Name & signature"),
            ("Head of institution", self.report.get("head_of_institution_name") or "Name & signature"),
            ("Parent / guardian", "Name & signature"),
        ]
        gap = 5
        box_w = (self.epw - gap * 2) / 3
        y = self.get_y()
        for index, (title, subtitle) in enumerate(labels):
            x = self.l_margin + index * (box_w + gap)
            self.set_draw_color(*_PDF_BORDER)
            self.set_line_width(0.4)
            self.line(x, y + 9.5, x + box_w, y + 9.5)
            self.set_xy(x, y + 11)
            self.set_font(self.font_family, "B", 7.0)
            self.set_text_color(*_PDF_NAVY)
            self.cell(box_w, 3.2, title)
            self.set_xy(x, y + 14.2)
            self.set_font(self.font_family, "B", 6.0)
            self.set_text_color(*_PDF_MUTED)
            self.cell(box_w, 3.0, _fit(self, subtitle, box_w, self.font_family, "B", 6.0))
        self.set_y(y + 20)

    def draw_matrix_table(self, sheet):
        _title, header, rows = _matrix_table_data(self.report, sheet, self.mode)
        display_header = []
        for heading in header:
            key = str(heading or "").casefold()
            if key == "pos":
                display_header.append("#")
            elif key == "admission no.":
                display_header.append("Adm. no.")
            elif key == "average":
                display_header.append("Avg")
            else:
                display_header.append(heading)

        col_count = len(display_header)
        font_size = 6.6 if col_count <= 12 else (5.8 if col_count <= 16 else 5.0)
        row_h = 5.0 if font_size >= 6.2 else 4.5
        widths = _matrix_fixed_widths(display_header, self.epw)

        def paint_header():
            self._paint_header_row(widths, display_header, row_h + 0.3, font_size)

        paint_header()
        for index, row in enumerate(rows):
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
                self.draw_matrix_letterhead(sheet, compact=True)
                paint_header()
            values = list(row) + [""] * (len(header) - len(row))
            values = values[: len(header)]

            is_mean = any(str(values[i]).casefold() == "class mean" for i in range(min(2, len(values))))
            fill = _PDF_MEAN if is_mean else (_PDF_ALT if index % 2 else _PDF_WHITE)
            x = self.l_margin
            y = self.get_y()
            for col_i, (width, value) in enumerate(zip(widths, values)):
                heading = str(display_header[col_i] or "").casefold()
                key = str(header[col_i] or "").casefold()
                is_summary = heading in {"total", "avg", "average", "grade"}
                if heading in {"grade", "total"} and not is_mean:
                    cell_fill = _PDF_GRADE
                elif is_summary and not is_mean:
                    cell_fill = _PDF_SUMMARY
                else:
                    cell_fill = fill
                align = "L" if heading in {"learner"} else "C"
                is_subject = key not in {
                    "pos",
                    "#",
                    "learner",
                    "class",
                    "admission no.",
                    "total",
                    "average",
                    "avg",
                    "grade",
                }
                if is_subject and self.mode == "graded":
                    self._paint_mark_grade_cell(
                        x, y, width, row_h, value, font_size=font_size, fill=cell_fill, align=align
                    )
                elif heading in {"grade", "total"} and not is_mean:
                    self._paint_grid_cell(
                        x,
                        y,
                        width,
                        row_h,
                        value,
                        font_size=font_size,
                        fill=cell_fill,
                        align=align,
                        text_color=self.primary,
                    )
                else:
                    is_empty = _pdf_text(value).strip() in {"", "-"}
                    self._paint_grid_cell(
                        x,
                        y,
                        width,
                        row_h,
                        value,
                        font_size=font_size,
                        fill=cell_fill,
                        align=align,
                        text_color=_PDF_EMPTY if is_empty else _PDF_INK,
                    )
                x += width
            if is_mean:
                self.set_draw_color(*_PDF_SUMMARY_EDGE)
                self.set_line_width(0.45)
                self.line(self.l_margin, y, self.w - self.r_margin, y)
            self.set_y(y + row_h)

    def draw_analytics_table(self, sheet):
        _title, header, rows = _analytics_table_data(self.report, sheet, self.mode)
        col_count = max(len(header), 1)
        font_size = 6.8 if col_count <= 10 else (6.0 if col_count <= 14 else (5.4 if col_count <= 18 else 4.8))
        row_h = 5.2 if font_size >= 6.0 else 4.6
        pos_w = min(7.0, self.epw * 0.04)
        class_w = min(28.0, self.epw * 0.14)
        sat_w = min(10.5, self.epw * 0.05)
        remaining = max(self.epw - pos_w - class_w - sat_w, 10)
        mark_count = max(col_count - 3, 1)
        mark_w = remaining / mark_count
        widths = [pos_w, class_w, sat_w] + [mark_w] * mark_count
        widths = widths[:col_count]

        def paint_header():
            self._paint_header_row(widths, header, row_h + 0.15, font_size)

        paint_header()
        left_cols = {1}
        for index, row in enumerate(rows):
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
                self.draw_matrix_letterhead(sheet, compact=True, kicker="SUBJECT ANALYTICS")
                paint_header()
            values = list(row) + [""] * (len(header) - len(row))
            values = values[: len(header)]
            is_mean = str(values[1] or "").casefold() in {"grade mean", "category mean"}
            fill = _PDF_MEAN if is_mean else (_PDF_ALT if index % 2 else _PDF_WHITE)
            x = self.l_margin
            y = self.get_y()
            for col_i, (width, value) in enumerate(zip(widths, values)):
                heading = str(header[col_i] or "").casefold()
                is_summary = heading in {"total", "mean", "grade"}
                if heading in {"grade", "total"} and not is_mean:
                    cell_fill = _PDF_GRADE
                elif is_summary and not is_mean:
                    cell_fill = _PDF_SUMMARY
                else:
                    cell_fill = fill
                align = "L" if col_i in left_cols else "C"
                is_subject_mark = col_i >= 3 and heading not in {"total", "mean", "grade"}
                if is_subject_mark and self.mode == "graded":
                    self._paint_mark_grade_cell(
                        x, y, width, row_h, value, font_size=font_size, fill=cell_fill, align=align
                    )
                elif heading in {"grade", "total"} and not is_mean:
                    self._paint_grid_cell(
                        x,
                        y,
                        width,
                        row_h,
                        value,
                        font_size=font_size,
                        fill=cell_fill,
                        align=align,
                        text_color=self.primary,
                    )
                else:
                    is_empty = _pdf_text(value).strip() in {"", "-"}
                    self._paint_grid_cell(
                        x,
                        y,
                        width,
                        row_h,
                        value,
                        font_size=font_size,
                        fill=cell_fill,
                        align=align,
                        text_color=_PDF_EMPTY if is_empty else _PDF_INK,
                    )
                x += width
            if is_mean:
                self.set_draw_color(*_PDF_SUMMARY_EDGE)
                self.set_line_width(0.45)
                self.line(self.l_margin, y, self.w - self.r_margin, y)
            self.set_y(y + row_h)


def build_exam_report_pdf(report, *, mode="raw"):
    if mode not in {"raw", "graded"}:
        mode = "raw"

    if report.get("is_matrix"):
        sheets = report.get("matrix_sheets") or [{}]
        pdf = PrintStyleExamPDF(report, mode, landscape=False)
        for sheet in sheets:
            pdf.add_page()
            pdf.draw_matrix_letterhead(sheet)
            pdf.draw_matrix_table(sheet)
    elif report.get("is_analytics"):
        sheets = report.get("analytics_sheets") or [{}]
        pdf = PrintStyleExamPDF(report, mode, landscape=False)
        for sheet in sheets:
            pdf.add_page()
            pdf.draw_matrix_letterhead(sheet, kicker="SUBJECT ANALYTICS")
            pdf.draw_analytics_table(sheet)
    else:
        cards = report.get("report_cards") or []
        pdf = PrintStyleExamPDF(report, mode, landscape=False)
        if not cards:
            pdf.add_page()
            pdf.set_font(pdf.font_family, "B", 11)
            pdf.set_text_color(*_PDF_MUTED)
            pdf.cell(0, 8, "No report data to export.", new_x="LMARGIN", new_y="NEXT")
        for card in cards:
            pdf.add_page()
            pdf.draw_card_letterhead(card)
            pdf.draw_summary(card)
            pdf.draw_results_table(card)
            pdf.draw_signoff()

    return bytes(pdf.output()), _export_filename(report, mode, "pdf")
