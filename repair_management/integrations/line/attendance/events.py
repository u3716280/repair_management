from __future__ import annotations


def preserve_line_selected_status(doc, method=None):
    """Keep Present/Absent selected in the LINE MINI App.

    HRMS Attendance.validate() normally reconciles Approved Leave and may
    replace the selected status with On Leave/Half Day. The LINE attendance
    flow intentionally ignores Approved Leave, so only documents explicitly
    flagged by this flow are restored after the standard controller validation.
    """
    selected_status = getattr(doc.flags, "line_mark_attendance_status", None)
    if selected_status not in {"Present", "Absent"}:
        return

    doc.status = selected_status
    doc.leave_type = None
    doc.leave_application = None
    if hasattr(doc, "half_day_status"):
        doc.half_day_status = None
