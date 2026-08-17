(() => {
    "use strict";

    const app = document.getElementById("attendance-app");
    if (!app) return;

    const configured = app.dataset.configured === "1";
    const channelName = app.dataset.channelName || "";
    const liffId = app.dataset.liffId || "";

    const configError = document.getElementById("config-error");
    const authError = document.getElementById("auth-error");
    const mainContent = document.getElementById("main-content");
    const dateInput = document.getElementById("attendance-date");
    const loading = document.getElementById("loading");
    const holiday = document.getElementById("holiday");
    const empty = document.getElementById("empty");
    const controls = document.getElementById("attendance-controls");
    const employeeList = document.getElementById("employee-list");
    const allPresentButton = document.getElementById("all-present");
    const submitButton = document.getElementById("submit-attendance");
    const submitErrors = document.getElementById("submit-errors");

    const state = {
        idToken: "",
        loadedDate: "",
        rows: [],
        submitting: false,
    };

    const apiBase =
        "/api/method/repair_management.integrations.line.attendance.api";

    const hide = (element) => element.classList.add("hidden");
    const show = (element) => element.classList.remove("hidden");

    const hasUnsavedChanges = () =>
        state.rows.some(
            (row) => !row.existing && row.status !== "Present",
        );

    function resetMessages() {
        hide(holiday);
        hide(empty);
        hide(submitErrors);
        submitErrors.innerHTML = "";
    }

    async function callApi(method, payload = {}) {
        const body = new URLSearchParams({
            id_token: state.idToken,
            channel_name: channelName,
            ...payload,
        });

        const response = await fetch(`${apiBase}.${method}`, {
            method: "POST",
            headers: {
                "Content-Type":
                    "application/x-www-form-urlencoded;charset=UTF-8",
            },
            body,
            credentials: "omit",
        });

        let data;

        try {
            data = await response.json();
        } catch (_error) {
            throw new Error("request_failed");
        }

        if (!response.ok || data.exc) {
            let message = "request_failed";

            if (data._server_messages) {
                try {
                    const messages = JSON.parse(data._server_messages);

                    if (messages.length) {
                        const parsed = JSON.parse(messages[0]);
                        message = parsed.message || message;
                    }
                } catch (_error) {
                    // Ignore parsing errors and fall back to exception text.
                }
            }

            if (
                message === "request_failed"
                && data.exception
            ) {
                message = data.exception;
            }

            throw new Error(message);
        }

        return data.message;
    }

    function setSelected(
        buttonPresent,
        buttonAbsent,
        status,
    ) {
        buttonPresent.classList.toggle(
            "selected-present",
            status === "Present",
        );

        buttonAbsent.classList.toggle(
            "selected-absent",
            status === "Absent",
        );

        buttonPresent.textContent =
            status === "Present" ? "✓ มา" : "มา";

        buttonAbsent.textContent =
            status === "Absent" ? "✓ ขาด" : "ขาด";
    }

    function renderRows() {
        employeeList.innerHTML = "";

        let editableCount = 0;

        state.rows.forEach((row) => {
            const item = document.createElement("article");
            item.className = "employee-row";

            const name = document.createElement("p");
            name.className = "employee-name";
            name.textContent = row.employee_name;
            item.appendChild(name);

            const id = document.createElement("div");
            id.className = "employee-id";
            id.textContent = row.employee;
            item.appendChild(id);

            if (row.existing) {
                const existingStatus =
                    document.createElement("div");

                existingStatus.className =
                    "existing-status";

                existingStatus.textContent =
                    `บันทึกแล้ว: ${row.status}`;

                item.appendChild(existingStatus);
            } else {
                editableCount += 1;

                const buttons =
                    document.createElement("div");

                buttons.className =
                    "status-buttons";

                const present =
                    document.createElement("button");

                present.type = "button";
                present.className =
                    "status-button";

                const absent =
                    document.createElement("button");

                absent.type = "button";
                absent.className =
                    "status-button";

                setSelected(
                    present,
                    absent,
                    row.status,
                );

                present.addEventListener(
                    "click",
                    () => {
                        if (
                            state.submitting
                            || row.status === "Present"
                        ) {
                            return;
                        }

                        row.status = "Present";

                        setSelected(
                            present,
                            absent,
                            row.status,
                        );
                    },
                );

                absent.addEventListener(
                    "click",
                    () => {
                        if (
                            state.submitting
                            || row.status === "Absent"
                        ) {
                            return;
                        }

                        row.status = "Absent";

                        setSelected(
                            present,
                            absent,
                            row.status,
                        );
                    },
                );

                buttons.append(
                    present,
                    absent,
                );

                item.appendChild(buttons);
            }

            employeeList.appendChild(item);
        });

        allPresentButton.classList.toggle(
            "hidden",
            editableCount === 0,
        );

        submitButton.classList.toggle(
            "hidden",
            editableCount === 0,
        );
    }

    function renderErrors(errors) {
        if (
            !errors
            || errors.length === 0
        ) {
            return;
        }

        const title =
            document.createElement("div");

        title.textContent =
            "บางรายการบันทึกไม่สำเร็จ";

        const list =
            document.createElement("ul");

        list.className = "error-list";

        errors.forEach((error) => {
            const item =
                document.createElement("li");

            item.textContent =
                `${error.employee_name} — บันทึกไม่สำเร็จ`;

            list.appendChild(item);
        });

        submitErrors.replaceChildren(
            title,
            list,
        );

        show(submitErrors);
    }

    async function loadAttendance(
        attendanceDate,
        errors = [],
    ) {
        resetMessages();
        hide(controls);
        show(loading);

        try {
            const view =
                await callApi(
                    "get_attendance",
                    {
                        attendance_date:
                            attendanceDate,
                    },
                );

            state.loadedDate =
                view.attendance_date;

            dateInput.value =
                view.attendance_date;

            state.rows =
                Array.isArray(view.employees)
                    ? view.employees
                    : [];

            hide(loading);

            if (view.holiday) {
                holiday.textContent =
                    view.holiday_message
                    || "วันนี้เป็นวันหยุด ไม่ต้อง Mark Attendance";

                show(holiday);
                return;
            }

            if (state.rows.length === 0) {
                show(empty);
                return;
            }

            renderRows();
            show(controls);
            renderErrors(errors);
        } catch (error) {
            hide(loading);

            submitErrors.textContent =
                error && error.message
                    ? error.message
                    : "ไม่สามารถโหลดข้อมูลได้";

            show(submitErrors);
        }
    }

    async function bootstrap() {
        if (
            !configured
            || !channelName
            || !liffId
        ) {
            show(configError);
            return;
        }

        try {
            await liff.init({
                liffId,
            });

            if (!liff.isLoggedIn()) {
                if (liff.isInClient()) {
                    throw new Error(
                        "LINE Login unavailable",
                    );
                }

                liff.login();
                return;
            }

            state.idToken =
                liff.getIDToken() || "";

            if (!state.idToken) {
                throw new Error(
                    "missing_id_token",
                );
            }

            const boot =
                await callApi("bootstrap");

            dateInput.min =
                boot.min_date;

            dateInput.max =
                boot.max_date;

            dateInput.value =
                boot.today;

            state.loadedDate =
                boot.today;

            show(mainContent);

            await loadAttendance(
                boot.today,
            );
        } catch (error) {
            hide(mainContent);

            authError.textContent =
                error && error.message
                    ? error.message
                    : "ไม่สามารถเข้าสู่ระบบได้";

            show(authError);
        }
    }

    dateInput.addEventListener(
        "change",
        async () => {
            const nextDate =
                dateInput.value;

            if (
                !nextDate
                || nextDate === state.loadedDate
            ) {
                return;
            }

            if (hasUnsavedChanges()) {
                const discard =
                    window.confirm(
                        "มีข้อมูลที่ยังไม่ได้บันทึก ต้องการทิ้งการเปลี่ยนแปลงและเปลี่ยนวันที่หรือไม่?",
                    );

                if (!discard) {
                    dateInput.value =
                        state.loadedDate;

                    return;
                }
            }

            await loadAttendance(
                nextDate,
            );
        },
    );

    allPresentButton.addEventListener(
        "click",
        () => {
            state.rows.forEach(
                (row) => {
                    if (
                        !row.existing
                        && row.status !== "Absent"
                    ) {
                        row.status =
                            "Present";
                    }
                },
            );

            renderRows();
        },
    );

    submitButton.addEventListener(
        "click",
        async () => {
            if (state.submitting) {
                return;
            }

            state.submitting = true;
            submitButton.disabled = true;
            allPresentButton.disabled = true;

            const originalText =
                submitButton.textContent;

            submitButton.textContent =
                "กำลังบันทึก...";

            hide(submitErrors);

            const selections =
                state.rows
                    .filter(
                        (row) => !row.existing,
                    )
                    .map(
                        (row) => ({
                            employee:
                                row.employee,
                            status:
                                row.status,
                        }),
                    );

            try {
                const result =
                    await callApi(
                        "submit_attendance",
                        {
                            attendance_date:
                                state.loadedDate,
                            selections:
                                JSON.stringify(
                                    selections,
                                ),
                        },
                    );

                await loadAttendance(
                    state.loadedDate,
                    result.errors || [],
                );
            } catch (error) {
                submitErrors.textContent =
                    error && error.message
                        ? error.message
                        : "บันทึกไม่สำเร็จ กรุณาลองอีกครั้ง";

                show(submitErrors);
            } finally {
                state.submitting = false;
                submitButton.disabled = false;
                allPresentButton.disabled = false;
                submitButton.textContent =
                    originalText;
            }
        },
    );

    window.addEventListener(
        "beforeunload",
        (event) => {
            if (
                !hasUnsavedChanges()
                || state.submitting
            ) {
                return;
            }

            event.preventDefault();
            event.returnValue = "";
        },
    );

    bootstrap();
})();
