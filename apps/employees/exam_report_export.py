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


def _format_analytics_mark(cell, mode):
    if not cell or cell.get("percent") is None:
        return "-"
    if mode == "graded" and cell.get("grade"):
        return f"{cell.get('percent')} ({cell.get('grade')})"
    return cell.get("percent")


def _analytics_table_data(report, sheet, mode):
    title = sheet.get("exam_title") or report.get("exam_title") or "Subject analytics"
    header = ["#", "Class", "Sat"]
    header.extend(
        getattr(subject, "code", None) or getattr(subject, "name", "") or "Subject"
        for subject in (sheet.get("subjects") or [])
    )
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

_PDF_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_PDF_NAVY = (15, 35, 63)
_PDF_INK = (16, 35, 63)
_PDF_MUTED = (90, 108, 132)
_PDF_LINE = (220, 228, 240)
_PDF_BORDER = (176, 190, 208)
_PDF_SOFT = (246, 249, 253)
_PDF_HEAD = (232, 239, 249)
_PDF_ALT = (250, 252, 255)
_PDF_MEAN = (226, 235, 248)
_PDF_SUMMARY = (236, 242, 251)
_PDF_BLUE = (27, 79, 214)
_PDF_WHITE = (255, 255, 255)


def _hex_to_rgb(value, fallback=_PDF_BLUE):
    raw = (value or "").strip().lstrip("#")
    if len(raw) != 6:
        return fallback
    try:
        return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def _mix_rgb(a, b, t=0.5):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


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


def _school_brand(report):
    profile = report.get("school_profile")
    if profile is None:
        return {
            "name": "Edu-Centric School",
            "motto": "",
            "contact": "",
            "logo_path": None,
            "initial": "E",
            "primary": _PDF_BLUE,
        }
    bits = []
    for part in (
        getattr(profile, "physical_address", "") or "",
        getattr(profile, "main_phone", "") or "",
        getattr(profile, "general_email", "") or "",
    ):
        cleaned = " ".join(str(part).split())
        if cleaned:
            bits.append(cleaned)
    logo_path = None
    try:
        if getattr(profile, "has_logo", False) and getattr(profile, "school_logo", None):
            logo_path = profile.school_logo.path
    except (OSError, ValueError, AttributeError):
        logo_path = None
    name = (
        getattr(profile, "brand_official_name", None)
        or getattr(profile, "official_name", None)
        or getattr(profile, "display_name", None)
        or "School"
    )
    initial = (getattr(profile, "display_name", None) or name or "E")[:1].upper()
    return {
        "name": name,
        "motto": (getattr(profile, "motto", None) or "").strip(),
        "contact": " · ".join(bits),
        "logo_path": logo_path,
        "initial": initial,
        "primary": _hex_to_rgb(getattr(profile, "primary_color", None)),
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


def _matrix_fixed_widths(header, usable_width):
    """Allocate fixed mm widths so Class / Grade / # never collapse."""
    fixed_map = {
        "pos": 7.5,
        "#": 7.5,
        "learner": 46,
        "class": 11,
        "admission no.": 15.5,
        "total": 11.5,
        "average": 12,
        "grade": 10,
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
    """PDF layout aligned with the on-screen / print report design."""

    def __init__(self, report, mode, *, landscape=False):
        super().__init__(orientation="L" if landscape else "P", unit="mm", format="A4")
        self.report = report
        self.mode = mode
        self.landscape = landscape
        self.brand = _school_brand(report)
        self.primary = self.brand["primary"]
        self.accent = _mix_rgb(self.primary, _PDF_NAVY, 0.35)
        self.font_family = "Helvetica"
        self._active_sheet = None
        self._active_card = None
        self.set_auto_page_break(auto=False, margin=10)
        self.set_margins(8, 7, 8)
        regular, bold = _resolve_pdf_fonts()
        if regular and bold:
            self.add_font("EduReport", "", regular)
            self.add_font("EduReport", "B", bold)
            self.font_family = "EduReport"

    def footer(self):
        self.set_y(-9)
        self.set_fill_color(*_PDF_SOFT)
        self.rect(0, self.h - 9, self.w, 9, "F")
        self.set_draw_color(*self.primary)
        self.set_line_width(0.45)
        self.line(0, self.h - 9, self.w, self.h - 9)
        self.set_y(-7.2)
        self.set_font(self.font_family, "", 6.6)
        self.set_text_color(*_PDF_MUTED)
        issued = self.report.get("issued_on")
        left = "  ·  ".join(
            part
            for part in (
                self.brand["name"].upper(),
                "With grades" if self.mode == "graded" else "Raw marks",
                issued.isoformat() if issued is not None else "",
            )
            if part
        )
        self.set_x(self.l_margin)
        self.cell(self.epw * 0.72, 4, left, align="L")
        self.cell(self.epw * 0.28, 4, f"Page {self.page_no()}", align="R")

    def _draw_logo_or_mark(self, x, y, size):
        if self.brand["logo_path"]:
            try:
                # Soft frame behind logo.
                self.set_fill_color(*_PDF_SOFT)
                self.set_draw_color(*_PDF_LINE)
                self.set_line_width(0.25)
                self.rect(x - 0.6, y - 0.6, size + 1.2, size + 1.2, "DF")
                self.image(self.brand["logo_path"], x=x, y=y, w=size, h=size)
                return
            except Exception:
                pass
        # Modern monogram badge.
        self.set_fill_color(*self.primary)
        self.rect(x, y, size, size, "F")
        inset = 1.1
        self.set_draw_color(*_PDF_WHITE)
        self.set_line_width(0.35)
        self.rect(x + inset, y + inset, size - inset * 2, size - inset * 2, "D")
        self.set_xy(x, y + size * 0.28)
        self.set_font(self.font_family, "B", max(size * 0.42, 8))
        self.set_text_color(*_PDF_WHITE)
        self.cell(size, size * 0.42, self.brand["initial"], align="C")

    def draw_matrix_letterhead(self, sheet, *, compact=False, kicker="ACADEMIC LEVEL MARK SHEET"):
        self._active_sheet = sheet
        top = self.get_y()
        logo = 10 if compact else 12
        # Balanced brand: logo left, mirror spacer right so title stays centered.
        self._draw_logo_or_mark(self.l_margin, top, logo)
        center_w = self.epw - (logo * 2) - 8
        cx = self.l_margin + logo + 4

        self.set_xy(cx, top + 0.1)
        self.set_font(self.font_family, "B", 5.8 if compact else 6.2)
        self.set_text_color(*self.primary)
        self.cell(center_w, 2.8, kicker, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_x(cx)
        self.set_font(self.font_family, "B", 8.6 if compact else 10)
        self.set_text_color(*_PDF_NAVY)
        self.cell(
            center_w,
            3.8 if compact else 4.4,
            _fit(self, self.brand["name"].upper(), center_w, self.font_family, "B", 8.6 if compact else 10),
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        if self.brand["motto"] and not compact:
            self.set_x(cx)
            self.set_font(self.font_family, "", 6.6)
            self.set_text_color(*_PDF_MUTED)
            self.cell(
                center_w,
                2.8,
                _fit(self, f'"{self.brand["motto"]}"', center_w, self.font_family, "", 6.6),
                align="C",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        if self.brand["contact"] and not compact:
            self.set_x(cx)
            self.set_font(self.font_family, "", 5.8)
            self.set_text_color(*_PDF_MUTED)
            self.cell(
                center_w,
                2.5,
                _fit(self, self.brand["contact"], center_w, self.font_family, "", 5.8),
                align="C",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        self.set_y(max(self.get_y(), top + logo) + (0.6 if compact else 1.0))
        self.set_draw_color(*self.primary)
        self.set_line_width(0.65)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.3)

        # Meta chip bar
        level = self.report.get("level")
        selected_class = self.report.get("selected_class")
        scope = getattr(level, "name", None) or ""
        if selected_class is not None:
            scope = f"{scope} · {selected_class.display_label}".strip(" ·")
        elif level is not None:
            scope = f"{scope} · whole grade".strip(" ·")
        chips = [
            sheet.get("section_title") or sheet.get("exam_title") or self.report.get("exam_title") or "",
            sheet.get("scope_label") or scope,
            f"{sheet.get('student_count') or len(sheet.get('rows') or [])} students",
            f"{sheet.get('subject_count') or len(sheet.get('subjects') or [])} subjects",
            "With grades" if self.mode == "graded" else "Raw marks",
        ]
        if sheet.get("overall_mean") is not None:
            chips.insert(-1, f"Mean {sheet.get('overall_mean')}")
        chips = [chip for chip in chips if chip]
        bar_h = 5.2
        y = self.get_y()
        self.set_fill_color(*_PDF_SOFT)
        self.set_draw_color(*_PDF_LINE)
        self.set_line_width(0.2)
        self.rect(self.l_margin, y, self.epw, bar_h, "DF")
        self.set_fill_color(*self.primary)
        self.rect(self.l_margin, y, 0.9, bar_h, "F")

        self.set_font(self.font_family, "B", 5.8)
        chip_x = self.l_margin + 2.6
        chip_y = y + 0.9
        for index, chip in enumerate(chips):
            label = _pdf_text(chip)
            width = self.get_string_width(label) + 3.4
            if chip_x + width > self.w - self.r_margin - 2:
                break
            self.set_xy(chip_x, chip_y)
            self.set_fill_color(*_PDF_WHITE)
            self.set_draw_color(*_PDF_LINE)
            self.set_text_color(*_PDF_NAVY)
            self.cell(width, 3.4, label, border=1, align="C", fill=True)
            chip_x += width + 1.2
            if index < len(chips) - 1 and chip_x < self.w - self.r_margin - 4:
                self.set_draw_color(*_PDF_BORDER)
                self.set_line_width(0.2)
                self.line(chip_x - 0.6, chip_y + 0.7, chip_x - 0.6, chip_y + 2.7)
        self.set_y(y + bar_h + 1.5)

    def draw_card_letterhead(self, card, *, compact=False):
        self._active_card = card
        top = self.get_y()
        usable = self.epw
        left_w = usable * 0.57
        right_w = usable - left_w - 3.5
        logo = 15 if compact else 18

        self._draw_logo_or_mark(self.l_margin, top, logo)
        tx = self.l_margin + logo + 3.2
        tw = left_w - logo - 3.2
        self.set_xy(tx, top)
        self.set_font(self.font_family, "B", 6.6)
        self.set_text_color(*self.primary)
        self.cell(tw, 3.3, "STUDENT PROGRESS REPORT", new_x="LMARGIN", new_y="NEXT")
        self.set_x(tx)
        self.set_font(self.font_family, "B", 10.5 if compact else 11.5)
        self.set_text_color(*_PDF_NAVY)
        self.cell(
            tw,
            4.8,
            _fit(self, self.brand["name"].upper(), tw, self.font_family, "B", 10.5 if compact else 11.5),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        if self.brand["motto"] and not compact:
            self.set_x(tx)
            self.set_font(self.font_family, "", 7.2)
            self.set_text_color(*_PDF_MUTED)
            self.cell(tw, 3.4, _fit(self, f'"{self.brand["motto"]}"', tw, self.font_family, "", 7.2), new_x="LMARGIN", new_y="NEXT")
        if self.brand["contact"] and not compact:
            self.set_x(tx)
            self.set_font(self.font_family, "", 6.5)
            self.set_text_color(*_PDF_MUTED)
            self.cell(tw, 3.2, _fit(self, self.brand["contact"], tw, self.font_family, "", 6.5), new_x="LMARGIN", new_y="NEXT")
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
            self.set_font(self.font_family, "B", 6.8)
            self.set_text_color(*_PDF_INK)
            self.cell(tw, 3.3, _fit(self, " · ".join(exam_bits), tw, self.font_family, "B", 6.8), new_x="LMARGIN", new_y="NEXT")
        left_bottom = max(self.get_y(), top + logo)

        student = card.get("student")
        rx = self.l_margin + left_w + 3.5
        # Soft learner panel
        panel_h = max(left_bottom - top, 22)
        self.set_fill_color(*_PDF_SOFT)
        self.set_draw_color(*_PDF_LINE)
        self.set_line_width(0.25)
        self.rect(rx - 1.2, top - 0.4, right_w + 2.2, panel_h + 0.8, "DF")
        self.set_fill_color(*self.primary)
        self.rect(rx - 1.2, top - 0.4, 1.05, panel_h + 0.8, "F")

        self.set_xy(rx + 1, top + 0.4)
        self.set_font(self.font_family, "B", 6.5)
        self.set_text_color(*self.primary)
        self.cell(right_w - 1, 3.2, "LEARNER", new_x="LMARGIN", new_y="NEXT")
        self.set_x(rx + 1)
        self.set_font(self.font_family, "B", 10.2)
        self.set_text_color(*_PDF_NAVY)
        name = student.display_name.upper() if student is not None else "LEARNER"
        self.cell(right_w - 1, 4.8, _fit(self, name, right_w - 1, self.font_family, "B", 10.2), new_x="LMARGIN", new_y="NEXT")

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
            self.set_x(rx + 1)
            self.set_font(self.font_family, "", 6.5)
            self.set_text_color(*_PDF_MUTED)
            self.cell(right_w * 0.38, 3.35, label)
            self.set_font(self.font_family, "B", 6.8)
            self.set_text_color(*_PDF_INK)
            self.cell(
                right_w * 0.58,
                3.35,
                _fit(self, value, right_w * 0.58, self.font_family, "B", 6.8),
                new_x="LMARGIN",
                new_y="NEXT",
            )

        bottom = max(left_bottom, top + panel_h) + 1.8
        self.set_y(bottom)
        self.set_draw_color(*self.primary)
        self.set_line_width(0.75)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2.8)

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

        gap = 1.6
        top_count = 3 if self.mode == "graded" else 2
        top_items = items[:top_count]
        remark_item = items[-1]
        box_w = (self.epw - gap * (top_count - 1)) / top_count
        y = self.get_y()
        h = 11.5
        for index, (label, value) in enumerate(top_items):
            x = self.l_margin + index * (box_w + gap)
            fill = _mix_rgb(self.primary, _PDF_WHITE, 0.88) if label == "Overall grade" else _PDF_SOFT
            self.set_fill_color(*fill)
            self.set_draw_color(*_PDF_LINE)
            self.set_line_width(0.25)
            self.rect(x, y, box_w, h, "DF")
            self.set_fill_color(*self.primary)
            self.rect(x, y, 1.0, h, "F")
            self.set_xy(x + 2.4, y + 1.5)
            self.set_font(self.font_family, "", 6.3)
            self.set_text_color(*_PDF_MUTED)
            self.cell(box_w - 4, 3, label.upper())
            self.set_xy(x + 2.4, y + 5.1)
            self.set_font(self.font_family, "B", 11)
            self.set_text_color(*_PDF_NAVY)
            self.cell(box_w - 4, 4.8, _fit(self, value, box_w - 4, self.font_family, "B", 11))
        self.set_y(y + h + gap)
        y = self.get_y()
        self.set_fill_color(*_PDF_SOFT)
        self.set_draw_color(*_PDF_LINE)
        self.rect(self.l_margin, y, self.epw, 10, "DF")
        self.set_fill_color(*self.primary)
        self.rect(self.l_margin, y, 1.0, 10, "F")
        self.set_xy(self.l_margin + 2.4, y + 1.2)
        self.set_font(self.font_family, "", 6.3)
        self.set_text_color(*_PDF_MUTED)
        self.cell(self.epw - 4, 3, remark_item[0].upper())
        self.set_xy(self.l_margin + 2.4, y + 4.5)
        self.set_font(self.font_family, "B", 8.4)
        self.set_text_color(*_PDF_INK)
        self.cell(self.epw - 4, 4, _fit(self, remark_item[1], self.epw - 4, self.font_family, "B", 8.4))
        self.set_y(y + 10 + 3)

    def _paint_header_row(self, widths, headers, row_h, font_size):
        x = self.l_margin
        y = self.get_y()
        self.set_fill_color(*self.accent)
        self.set_draw_color(*self.accent)
        self.set_text_color(*_PDF_WHITE)
        self.set_font(self.font_family, "B", font_size)
        for width, heading in zip(widths, headers):
            self.set_xy(x, y)
            label = _fit(self, heading, width, self.font_family, "B", font_size)
            self.cell(width, row_h, label, border=0, align="C", fill=True)
            x += width
        # Bottom edge under header
        self.set_draw_color(*self.primary)
        self.set_line_width(0.35)
        self.line(self.l_margin, y + row_h, self.w - self.r_margin, y + row_h)
        self.set_y(y + row_h)

    def draw_results_table(self, card):
        self.set_font(self.font_family, "B", 7.4)
        self.set_text_color(*self.primary)
        self.cell(self.epw, 4.2, "ASSESSMENT RESULTS", new_x="LMARGIN", new_y="NEXT")
        self.ln(0.6)

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
        font_size = 7.1 if col_count <= 6 else (6.3 if col_count <= 10 else 5.5)
        row_h = 6.0 if font_size >= 7 else 5.2
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
        for index, values in enumerate(rows):
            if self.get_y() + row_h > self.h - self.b_margin - 26:
                self.add_page()
                self.draw_card_letterhead(card, compact=True)
                self.set_font(self.font_family, "B", 7.4)
                self.set_text_color(*self.primary)
                self.cell(self.epw, 4.2, "ASSESSMENT RESULTS (continued)", new_x="LMARGIN", new_y="NEXT")
                self.ln(0.6)
                self._paint_header_row(widths, headers, row_h, font_size)
            x = self.l_margin
            y = self.get_y()
            fill = _PDF_ALT if index % 2 else _PDF_WHITE
            self.set_fill_color(*fill)
            self.set_draw_color(*_PDF_LINE)
            self.set_text_color(*_PDF_INK)
            for col_i, (width, value) in enumerate(zip(widths, values)):
                self.set_xy(x, y)
                style = "B" if col_i == 0 else ""
                self.set_font(self.font_family, style, font_size)
                align = "L" if col_i in {0, col_count - 1} else "C"
                self.cell(
                    width,
                    row_h,
                    _fit(self, value, width, self.font_family, style, font_size),
                    border="B",
                    align=align,
                    fill=True,
                )
                x += width
            self.set_y(y + row_h)

        if card.get("mean_percent") is not None:
            x = self.l_margin
            y = self.get_y()
            self.set_fill_color(*_PDF_MEAN)
            self.set_font(self.font_family, "B", font_size)
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
            for width, value in zip(widths, mean_values):
                self.set_xy(x, y)
                self.set_text_color(*_PDF_NAVY)
                self.cell(
                    width,
                    row_h,
                    _fit(self, value, width, self.font_family, "B", font_size),
                    border="B",
                    align="C",
                    fill=True,
                )
                x += width
            self.set_y(y + row_h)
        self.ln(4)

    def draw_signoff(self):
        if self.get_y() + 26 > self.h - self.b_margin:
            self.add_page()
            if self._active_card is not None:
                self.draw_card_letterhead(self._active_card, compact=True)
        self.set_draw_color(*_PDF_LINE)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3.2)
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
            self.set_line_width(0.5)
            self.line(x, y + 9.5, x + box_w, y + 9.5)
            self.set_xy(x, y + 11)
            self.set_font(self.font_family, "B", 7.3)
            self.set_text_color(*_PDF_NAVY)
            self.cell(box_w, 3.4, title)
            self.set_xy(x, y + 14.4)
            self.set_font(self.font_family, "", 6.3)
            self.set_text_color(*_PDF_MUTED)
            self.cell(box_w, 3.1, _fit(self, subtitle, box_w, self.font_family, "", 6.3))
        self.set_y(y + 20)

    def draw_matrix_table(self, sheet):
        _title, header, rows = _matrix_table_data(self.report, sheet, self.mode)
        # Friendlier short labels that still fit.
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
        font_size = 6.8 if col_count <= 12 else (6.0 if col_count <= 16 else 5.2)
        row_h = 5.2 if font_size >= 6.6 else 4.6
        widths = _matrix_fixed_widths(display_header, self.epw)
        summary_keys = {"total", "avg", "average", "grade"}

        def paint_header():
            self._paint_header_row(widths, display_header, row_h + 0.4, font_size)

        paint_header()
        for index, row in enumerate(rows):
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
                self.draw_matrix_letterhead(sheet, compact=True)
                paint_header()
            values = list(row) + [""] * (len(header) - len(row))
            values = values[: len(header)]
            # Format graded subject cells with parentheses for consistency.
            if self.mode == "graded":
                for col_i, heading in enumerate(header):
                    key = str(heading or "").casefold()
                    if key in {"pos", "learner", "class", "admission no.", "total", "average", "grade"}:
                        continue
                    text = _pdf_text(values[col_i])
                    # Convert "88 (A)" already ok; "88 A" from excel helper uses "88 (A)" via _format_mark_cell
                    values[col_i] = text

            is_mean = any(str(values[i]).casefold() == "class mean" for i in range(min(2, len(values))))
            fill = _PDF_MEAN if is_mean else (_PDF_ALT if index % 2 else _PDF_WHITE)
            x = self.l_margin
            y = self.get_y()
            self.set_draw_color(*_PDF_LINE)
            self.set_text_color(*_PDF_INK)
            for col_i, (width, value) in enumerate(zip(widths, values)):
                heading = str(display_header[col_i] or "").casefold()
                is_summary = heading in summary_keys
                cell_fill = _PDF_SUMMARY if is_summary and not is_mean else fill
                self.set_fill_color(*cell_fill)
                style = "B" if is_mean or heading in {"learner", "#"} or is_summary else ""
                self.set_font(self.font_family, style, font_size)
                align = "L" if heading in {"learner"} else "C"
                self.set_xy(x, y)
                self.cell(
                    width,
                    row_h,
                    _fit(self, value, width, self.font_family, style, font_size),
                    border="B",
                    align=align,
                    fill=True,
                )
                x += width
            self.set_y(y + row_h)

    def draw_analytics_table(self, sheet):
        _title, header, rows = _analytics_table_data(self.report, sheet, self.mode)
        col_count = len(header)
        font_size = 6.8 if col_count <= 12 else (6.0 if col_count <= 16 else 5.2)
        row_h = 5.2 if font_size >= 6.6 else 4.6
        weights = []
        for i, heading in enumerate(header):
            longest = max(len(str(heading)), 3)
            for row in rows[:20]:
                if i < len(row):
                    longest = max(longest, len(str(row[i])))
            prefer = 1.8 if i == 1 else (1.15 if i in {0, 2} else 1.0)
            weights.append(longest * prefer)
        total = sum(weights) or 1
        widths = [self.epw * (weight / total) for weight in weights]

        def paint_header():
            self._paint_header_row(widths, header, row_h + 0.3, font_size)

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
            self.set_draw_color(*_PDF_LINE)
            self.set_text_color(*_PDF_INK)
            for col_i, (width, value) in enumerate(zip(widths, values)):
                heading = str(header[col_i] or "").casefold()
                is_summary = heading in {"total", "mean", "grade"}
                self.set_fill_color(*(_PDF_SUMMARY if is_summary and not is_mean else fill))
                style = "B" if col_i in {0, 1} or is_summary or is_mean else ""
                self.set_font(self.font_family, style, font_size)
                self.set_xy(x, y)
                self.cell(
                    width,
                    row_h,
                    _fit(self, value, width, self.font_family, style, font_size),
                    border="B",
                    align="L" if col_i in left_cols else "C",
                    fill=True,
                )
                x += width
            self.set_y(y + row_h)


def build_exam_report_pdf(report, *, mode="raw"):
    if mode not in {"raw", "graded"}:
        mode = "raw"

    if report.get("is_matrix"):
        sheets = report.get("matrix_sheets") or [{}]
        max_subjects = max((len(sheet.get("subjects") or []) for sheet in sheets), default=0)
        landscape = max_subjects >= 4 or bool(report.get("show_class_column"))
        pdf = PrintStyleExamPDF(report, mode, landscape=landscape)
        for sheet in sheets:
            pdf.add_page()
            pdf.draw_matrix_letterhead(sheet)
            pdf.draw_matrix_table(sheet)
    elif report.get("is_analytics"):
        sheets = report.get("analytics_sheets") or [{}]
        max_subjects = max((len(sheet.get("subjects") or []) for sheet in sheets), default=0)
        pdf = PrintStyleExamPDF(report, mode, landscape=max_subjects >= 4)
        for sheet in sheets:
            pdf.add_page()
            pdf.draw_matrix_letterhead(sheet, kicker="SUBJECT ANALYTICS")
            pdf.draw_analytics_table(sheet)
    else:
        cards = report.get("report_cards") or []
        pdf = PrintStyleExamPDF(report, mode, landscape=False)
        if not cards:
            pdf.add_page()
            pdf.set_font(pdf.font_family, "", 11)
            pdf.set_text_color(*_PDF_MUTED)
            pdf.cell(0, 8, "No report data to export.", new_x="LMARGIN", new_y="NEXT")
        for card in cards:
            pdf.add_page()
            pdf.draw_card_letterhead(card)
            pdf.draw_summary(card)
            pdf.draw_results_table(card)
            pdf.draw_signoff()

    return bytes(pdf.output()), _export_filename(report, mode, "pdf")
