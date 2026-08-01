/*
 * app.js — the entire frontend logic for the Jummikville Fee Management System.
 *
 * WHY ONE FILE, NO BUILD STEP:
 * This app is intentionally a single static folder served by the FastAPI backend.
 * There's no npm, no bundler, no compile step — just HTML + this file + a CDN or
 * two. That makes it easy for someone new to frontends to read top-to-bottom and
 * maintain, and it means "deploying the frontend" is just "the backend serves a
 * folder". Interactivity is handled by Alpine.js (loaded in index.html); this
 * file provides the data layer and the Alpine component objects.
 *
 * HOW IT'S ORGANISED:
 *   1. CONFIG        — the one school id + API base
 *   2. api()         — a tiny fetch wrapper so every call looks the same
 *   3. helpers       — formatting, status colours, "time ago"
 *   4. Alpine stores/components — one per screen, referenced from index.html
 */

// ---------------------------------------------------------------------------
// 1. CONFIG
// ---------------------------------------------------------------------------
// The backend is multi-school, but this UI drives ONE school. Seeded data uses
// id 1 (Jummikville Academy). If you ever run this for a different school,
// change this single number.
const CONFIG = {
  SCHOOL_ID: 1,
  // Same-origin: the frontend is served by the same server as the API, so we
  // can use a relative path and never worry about CORS or hardcoded hosts.
  API_BASE: "/api/v1",
};

// ---------------------------------------------------------------------------
// 2. api() — one wrapper for every backend call
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const url = `${CONFIG.API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    // Send the httpOnly session cookie on every request. It's same-origin so
    // this is the default, but we're explicit so the intent is obvious.
    credentials: "same-origin",
    ...options,
  });

  if (!res.ok) {
    // A 401 means the session is missing or expired. Bounce the user back to
    // the login screen — except on the auth endpoints themselves, which handle
    // their own 401s (a failed login shouldn't trigger the "session expired"
    // path, and /auth/me returning 401 is the normal "not logged in" signal).
    if (res.status === 401 && !path.startsWith("/auth/")) {
      const auth = window.Alpine && Alpine.store("auth");
      if (auth) auth.onUnauthorized();
    }

    // Try to surface the backend's error detail; fall back to a generic message.
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }

  // 204 No Content or empty body → return null instead of throwing on .json()
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

// ---------------------------------------------------------------------------
// 3. Small helpers
// ---------------------------------------------------------------------------

// Map a status string to Tailwind classes for the coloured pill/badge.
function statusBadge(status) {
  switch (status) {
    case "paid":
      return { label: "Paid", cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" };
    case "overpaid":
      // Overpaid is its OWN status — the parent paid more than owed. Blue so it
      // reads as "money to return", clearly distinct from a plain green "Paid".
      return { label: "Overpaid", cls: "bg-sky-50 text-sky-700 ring-sky-600/20" };
    case "partial":
      return { label: "Partially Paid", cls: "bg-amber-50 text-amber-700 ring-amber-600/20" };
    case "no_fee":
      // No fees assigned yet — NOT the same as fully paid. Neutral slate colour
      // so it reads as "needs attention / incomplete", not success or debt.
      return { label: "No fee set", cls: "bg-slate-100 text-slate-600 ring-slate-500/20" };
    case "unpaid":
      return { label: "Unpaid", cls: "bg-rose-50 text-rose-700 ring-rose-600/20" };
    default:
      return { label: "Unpaid", cls: "bg-rose-50 text-rose-700 ring-rose-600/20" };
  }
}

// Format an integer kobo amount as "₦75,000". Shared so every screen formats
// money the same way. (The backend also sends *_display strings for most values;
// this is for the few places we only have raw kobo, like the fee-type default.)
function nairaFromKobo(kobo) {
  return "₦" + (Number(kobo || 0) / 100).toLocaleString("en-NG");
}

// Icon (emoji, to stay dependency-free) for each activity type.
function activityIcon(action) {
  switch (action) {
    case "payment_recorded":
      return "✅";
    case "reminder_sent":
      return "📩";
    default:
      return "•";
  }
}

// "3 minutes ago" style relative time from an ISO timestamp.
function timeAgo(isoString) {
  const then = new Date(isoString);
  const seconds = Math.floor((Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return then.toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" });
}

// A readable date-time, e.g. "31 Jul 2026, 2:15 PM"
function formatDateTime(isoString) {
  return new Date(isoString).toLocaleString("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// 4. Alpine components — one object per screen
// ---------------------------------------------------------------------------
// Registered on the `alpine:init` event so they're available to x-data in HTML.
document.addEventListener("alpine:init", () => {
  // -- Global app shell: which screen is showing, plus a toast notifier -------
  Alpine.store("app", {
    screen: "dashboard", // 'dashboard' | 'parents' | 'setup' | 'activity'
    toast: { show: false, message: "", kind: "success" },

    go(screen) {
      this.screen = screen;
    },

    notify(message, kind = "success") {
      this.toast = { show: true, message, kind };
      setTimeout(() => (this.toast.show = false), 4000);
    },
  });

  // -- Auth store: who's logged in, plus login/logout + idle timeout ----------
  // The whole app is gated behind this. On load we ask the backend "who am I?"
  // (GET /auth/me); a 200 shows the app, a 401 shows the login screen. The
  // session token lives in an httpOnly cookie we never touch from JS — we only
  // track the *state* (logged in or not) here.
  Alpine.store("auth", {
    // 'checking' while the initial /me call is in flight, so we don't flash the
    // login form before we know whether there's already a valid session.
    status: "checking", // 'checking' | 'in' | 'out'
    user: null,

    // Idle timeout mirrors the backend's sliding session. If the user does
    // nothing for this long, we log them out client-side too so the UI matches
    // reality (the cookie would have expired anyway). Kept a touch under the
    // backend's 30 min so the UI never shows stale "logged in" state.
    IDLE_MINUTES: 30,
    _idleTimer: null,

    get isAuthenticated() {
      return this.status === "in";
    },

    async init() {
      try {
        this.user = await api("/auth/me");
        this.status = "in";
        this._startIdleWatch();
      } catch (_) {
        // 401 (or anything else) → treat as logged out and show the login form.
        this.status = "out";
        this.user = null;
      }
    },

    async login(email, password) {
      // Throws on failure so the login form can show the message; the caller
      // (loginForm) handles the try/catch and error display.
      this.user = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      this.status = "in";
      this._startIdleWatch();
      // Land on the dashboard after a fresh login.
      Alpine.store("app").go("dashboard");
    },

    async logout() {
      try {
        await api("/auth/logout", { method: "POST" });
      } catch (_) {
        /* even if the call fails, we still clear local state below */
      }
      this._endSession();
      Alpine.store("app").notify("You've been logged out.");
    },

    // Called by api() when any protected request comes back 401 — the session
    // expired or was revoked server-side mid-use.
    onUnauthorized() {
      if (this.status === "out") return; // already showing the login screen
      this._endSession();
      Alpine.store("app").notify("Your session expired. Please log in again.", "error");
    },

    // Shared teardown for logout and expiry.
    _endSession() {
      this.status = "out";
      this.user = null;
      this._stopIdleWatch();
    },

    // --- idle timeout: any activity resets the countdown ---
    _startIdleWatch() {
      this._stopIdleWatch();
      const reset = () => this._resetIdle();
      // Store the handler so we can remove exactly it later.
      this._idleReset = reset;
      ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((evt) =>
        window.addEventListener(evt, reset, { passive: true })
      );
      this._resetIdle();
    },

    _resetIdle() {
      if (this._idleTimer) clearTimeout(this._idleTimer);
      this._idleTimer = setTimeout(() => {
        // Idle limit hit — clear the session and tell the user why.
        this._endSession();
        Alpine.store("app").notify("Logged out after 30 minutes of inactivity.", "error");
      }, this.IDLE_MINUTES * 60 * 1000);
    },

    _stopIdleWatch() {
      if (this._idleTimer) {
        clearTimeout(this._idleTimer);
        this._idleTimer = null;
      }
      if (this._idleReset) {
        ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((evt) =>
          window.removeEventListener(evt, this._idleReset)
        );
        this._idleReset = null;
      }
    },
  });

  // -- Login form component (used by the login screen) ------------------------
  Alpine.data("loginForm", () => ({
    email: "",
    password: "",
    submitting: false,
    error: "",

    async submit() {
      if (this.submitting) return;
      this.error = "";
      if (!this.email.trim() || !this.password) {
        this.error = "Enter your email and password.";
        return;
      }
      this.submitting = true;
      try {
        await Alpine.store("auth").login(this.email.trim(), this.password);
        // Clear the password from memory once we're in.
        this.password = "";
      } catch (e) {
        this.error = e.message || "Login failed. Please try again.";
      } finally {
        this.submitting = false;
      }
    },
  }));

  // -- Dashboard screen -------------------------------------------------------
  Alpine.data("dashboard", () => ({
    loading: true,
    sending: false,
    summary: null,
    recent: [],
    chart: null,
    section: "all", // 'all' | 'Nursery' | 'Primary' | 'Secondary'

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        // The section filter is passed to the backend so the 4 totals, the
        // status counts, and the category breakdown are all scoped to it.
        // 'all' means whole-school (no section param).
        const sectionQ = this.section === "all" ? "" : `&section=${encodeURIComponent(this.section)}`;
        const [summary, recent] = await Promise.all([
          api(`/dashboard/summary?school_id=${CONFIG.SCHOOL_ID}${sectionQ}`),
          api(`/activity/?school_id=${CONFIG.SCHOOL_ID}&limit=6`),
        ]);
        this.summary = summary;
        this.recent = recent || [];
        // Draw the chart on the next tick, once the <canvas> is in the DOM.
        this.$nextTick(() => this.drawChart());
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // Switch the whole dashboard to a section (or back to whole-school).
    async switchSection(section) {
      if (this.section === section) return;
      this.section = section;
      await this.load();
    },

    drawChart() {
      const canvas = this.$refs.paidChart;
      if (!canvas || !this.summary) return;
      if (this.chart) this.chart.destroy(); // redraw cleanly on reload

      this.chart = new Chart(canvas, {
        type: "doughnut",
        data: {
          labels: ["Fully Paid", "Overpaid", "Partially Paid", "Unpaid", "No fee set"],
          datasets: [
            {
              data: [
                this.summary.students_paid,
                this.summary.students_overpaid || 0,
                this.summary.students_partial,
                this.summary.students_unpaid,
                this.summary.students_no_fee || 0,
              ],
              // emerald, sky, amber, rose, slate — sky matches the "Overpaid" badge
              backgroundColor: ["#059669", "#0284c7", "#d97706", "#e11d48", "#94a3b8"],
              borderWidth: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "68%",
          plugins: {
            legend: { position: "bottom", labels: { padding: 16, usePointStyle: true } },
          },
        },
      });
    },

    // The "Send Reminders Now" button — triggers the real WhatsApp flow.
    async sendReminders() {
      if (this.sending) return;
      const outstanding = this.summary?.students_partial + this.summary?.students_unpaid;
      if (!confirm(
        `Send a WhatsApp reminder to every parent with an outstanding balance` +
        (outstanding ? ` (about ${outstanding} student${outstanding === 1 ? "" : "s"})?` : "?")
      )) return;

      this.sending = true;
      try {
        // include_payment_link=false → WhatsApp reminder only, no Paystack link.
        const result = await api(
          `/reminders/send?school_id=${CONFIG.SCHOOL_ID}&include_payment_link=false`,
          { method: "POST" }
        );
        Alpine.store("app").notify(result.message || "Reminders sent.");
        await this.load(); // refresh the mini-feed so the new entries show
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.sending = false;
      }
    },

    // expose helpers to the template
    activityIcon,
    timeAgo,
    nairaFromKobo,
  }));

  // -- Parents / Students screen ---------------------------------------------
  Alpine.data("parents", () => ({
    loading: true,
    students: [],
    search: "",
    statusFilter: "all", // 'all' | 'paid' | 'partial' | 'unpaid' | 'overpaid'
    sectionFilter: "all", // 'all' | 'Nursery' | 'Primary' | 'Secondary'

    // detail drawer
    drawerOpen: false,
    detailLoading: false,
    detail: null,

    // manual payment modal
    payOpen: false,
    paySubmitting: false,
    payForm: { fee_record_id: "", amount_naira: "", method: "cash", recorded_by: "", note: "" },

    // add-student modal. A fee type + amount are REQUIRED here so a student can
    // never be created with no fees set (which used to look misleadingly "paid").
    addOpen: false,
    addSubmitting: false,
    addForm: {
      student_name: "", section: "Primary", class_name: "", parent_name: "", parent_phone: "", parent_email: "",
      fee_type_id: "", amount_naira: "",
    },

    // edit-student modal
    editOpen: false,
    editSubmitting: false,
    editForm: { id: null, student_name: "", section: "Primary", class_name: "", parent_name: "", parent_phone: "", parent_email: "" },

    // assign-fee modal
    assignOpen: false,
    assignSubmitting: false,
    feeTypes: [],
    assignForm: { student_id: null, student_name: "", fee_type_id: "", amount_naira: "" },

    // per-parent reminder
    remindingId: null,

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        this.students = await api(`/dashboard/students?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    get filtered() {
      const q = this.search.trim().toLowerCase();
      return this.students.filter((s) => {
        const matchesText =
          !q ||
          s.student_name.toLowerCase().includes(q) ||
          s.parent_name.toLowerCase().includes(q) ||
          (s.parent_phone || "").includes(q);
        const matchesStatus = this.statusFilter === "all" || s.status === this.statusFilter;
        const matchesSection = this.sectionFilter === "all" || s.section === this.sectionFilter;
        return matchesText && matchesStatus && matchesSection;
      });
    },

    statusBadge,
    nairaFromKobo,

    // --- detail drawer ---
    async openDetail(studentId) {
      this.drawerOpen = true;
      this.detailLoading = true;
      this.detail = null;
      try {
        this.detail = await api(`/dashboard/students/${studentId}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
        this.drawerOpen = false;
      } finally {
        this.detailLoading = false;
      }
    },

    closeDetail() {
      this.drawerOpen = false;
    },

    // --- manual (cash/POS) payment ---
    // Opens the modal pre-scoped to a student. We let staff pick which fee line
    // the payment applies to (a student can owe tuition AND books).
    openPayment(student) {
      this.payForm = {
        student_name: student.student_name,
        fee_record_id: "",
        amount_naira: "",
        method: "cash",
        recorded_by: "",
        note: "",
      };
      // We need this student's fee lines to choose from — reuse the detail call.
      this.payFeeLines = [];
      api(`/dashboard/students/${student.student_id}`)
        .then((d) => {
          // Only show lines that still have a balance to pay.
          this.payFeeLines = (d.fee_records || []).filter(
            (r) => (r.remaining_kobo ?? r.balance_kobo) > 0
          );
          if (this.payFeeLines.length === 1) {
            this.payForm.fee_record_id = this.payFeeLines[0].fee_record_id;
          }
        })
        .catch((e) => Alpine.store("app").notify(e.message, "error"));
      this.payOpen = true;
    },
    payFeeLines: [],

    closePayment() {
      this.payOpen = false;
    },

    async submitPayment() {
      if (this.paySubmitting) return;
      const naira = parseFloat(this.payForm.amount_naira);
      if (!this.payForm.fee_record_id) {
        Alpine.store("app").notify("Please choose which fee this payment is for.", "error");
        return;
      }
      if (!naira || naira <= 0) {
        Alpine.store("app").notify("Enter a valid amount.", "error");
        return;
      }
      if (!this.payForm.recorded_by.trim()) {
        Alpine.store("app").notify("Enter who is recording this payment.", "error");
        return;
      }

      this.paySubmitting = true;
      try {
        await api(`/payments/cash`, {
          method: "POST",
          body: JSON.stringify({
            fee_record_id: Number(this.payForm.fee_record_id),
            amount_kobo: Math.round(naira * 100), // naira → kobo for the backend
            method: this.payForm.method,
            recorded_by: this.payForm.recorded_by.trim(),
            note: this.payForm.note.trim() || null,
          }),
        });
        Alpine.store("app").notify(
          `Payment recorded. A WhatsApp confirmation has been sent to the parent.`
        );
        this.payOpen = false;
        await this.load(); // refresh balances in the table
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.paySubmitting = false;
      }
    },

    // --- add a new student (with a required fee assignment) ---
    openAdd() {
      this.addForm = {
        student_name: "",
        section: "Primary",
        class_name: "",
        parent_name: "",
        parent_phone: "",
        parent_email: "",
        fee_type_id: "",
        amount_naira: "",
      };
      // Load the fee-type catalog so the form can pick one.
      this.feeTypes = [];
      api(`/fees/types?school_id=${CONFIG.SCHOOL_ID}`)
        .then((types) => {
          this.feeTypes = types || [];
        })
        .catch((e) => Alpine.store("app").notify(e.message, "error"));
      this.addOpen = true;
    },

    closeAdd() {
      this.addOpen = false;
    },

    async submitAdd() {
      if (this.addSubmitting) return;
      if (!this.addForm.student_name.trim()) {
        Alpine.store("app").notify("Enter the student's name.", "error");
        return;
      }
      if (!this.addForm.section) {
        Alpine.store("app").notify("Choose a section.", "error");
        return;
      }
      if (!this.addForm.parent_name.trim()) {
        Alpine.store("app").notify("Enter the parent's name.", "error");
        return;
      }
      if (!this.addForm.parent_phone.trim()) {
        Alpine.store("app").notify("Enter the parent's phone number.", "error");
        return;
      }
      // Fees are REQUIRED — this is what stops a student being created with a
      // misleading "No fee set" status by accident.
      if (!this.addForm.fee_type_id) {
        Alpine.store("app").notify("Choose a fee type for this student.", "error");
        return;
      }
      const feeNaira = parseFloat(this.addForm.amount_naira);
      if (!feeNaira || feeNaira <= 0) {
        Alpine.store("app").notify("Enter the total fees for this student.", "error");
        return;
      }

      this.addSubmitting = true;
      try {
        // Step 1: create the student.
        const student = await api(`/students/`, {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            student_name: this.addForm.student_name.trim(),
            section: this.addForm.section,
            class_name: this.addForm.class_name.trim() || null,
            parent_name: this.addForm.parent_name.trim(),
            parent_phone: this.addForm.parent_phone.trim(),
            parent_email: this.addForm.parent_email.trim() || null,
          }),
        });

        // Step 2: assign the required fee to the new student. If this fails we
        // surface it clearly — the student exists but has no fee yet, and will
        // show as "No fee set" so the gap is visible rather than hidden.
        try {
          await api(`/fees/records`, {
            method: "POST",
            body: JSON.stringify({
              student_id: student.id,
              fee_type_id: Number(this.addForm.fee_type_id),
              total_fees_kobo: Math.round(feeNaira * 100),
            }),
          });
          Alpine.store("app").notify("Student added and fee assigned.");
        } catch (feeErr) {
          Alpine.store("app").notify(
            `Student added, but assigning the fee failed: ${feeErr.message}. ` +
            `You can assign it from their record.`,
            "error"
          );
        }

        this.addOpen = false;
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.addSubmitting = false;
      }
    },

    // --- edit an existing student (opened from the detail drawer) ---
    openEdit() {
      if (!this.detail) return;
      this.editForm = {
        id: this.detail.student_id,
        student_name: this.detail.student_name || "",
        section: this.detail.section || "Primary",
        class_name: this.detail.class_name || "",
        parent_name: this.detail.parent_name || "",
        parent_phone: this.detail.parent_phone || "",
        parent_email: this.detail.parent_email || "",
      };
      this.editOpen = true;
    },

    closeEdit() {
      this.editOpen = false;
    },

    async submitEdit() {
      if (this.editSubmitting) return;
      if (!this.editForm.student_name.trim()) {
        Alpine.store("app").notify("Enter the student's name.", "error");
        return;
      }
      if (!this.editForm.parent_phone.trim()) {
        Alpine.store("app").notify("Enter the parent's phone number.", "error");
        return;
      }

      this.editSubmitting = true;
      try {
        await api(`/students/${this.editForm.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            student_name: this.editForm.student_name.trim(),
            section: this.editForm.section,
            class_name: this.editForm.class_name.trim() || null,
            parent_name: this.editForm.parent_name.trim(),
            parent_phone: this.editForm.parent_phone.trim(),
            parent_email: this.editForm.parent_email.trim() || null,
          }),
        });
        Alpine.store("app").notify("Student updated.");
        this.editOpen = false;
        await this.load();
        // Refresh the open drawer so it reflects the new details.
        await this.openDetail(this.editForm.id);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.editSubmitting = false;
      }
    },

    // --- assign a fee to the student in the open drawer ---
    openAssign() {
      if (!this.detail) return;
      this.assignForm = {
        student_id: this.detail.student_id,
        student_name: this.detail.student_name,
        fee_type_id: "",
        amount_naira: "",
      };
      // Load this school's fee-type catalog to pick from.
      this.feeTypes = [];
      api(`/fees/types?school_id=${CONFIG.SCHOOL_ID}`)
        .then((types) => {
          this.feeTypes = types || [];
        })
        .catch((e) => Alpine.store("app").notify(e.message, "error"));
      this.assignOpen = true;
    },

    closeAssign() {
      this.assignOpen = false;
    },

    // When a fee type is chosen, pre-fill the amount with its default.
    onAssignFeeTypeChange() {
      const chosen = this.feeTypes.find(
        (t) => String(t.id) === String(this.assignForm.fee_type_id)
      );
      if (chosen) {
        this.assignForm.amount_naira = (chosen.amount_kobo / 100).toString();
      }
    },

    async submitAssign() {
      if (this.assignSubmitting) return;
      if (!this.assignForm.fee_type_id) {
        Alpine.store("app").notify("Choose a fee type.", "error");
        return;
      }
      const naira = parseFloat(this.assignForm.amount_naira);
      if (!naira || naira <= 0) {
        Alpine.store("app").notify("Enter a valid amount.", "error");
        return;
      }

      this.assignSubmitting = true;
      try {
        await api(`/fees/records`, {
          method: "POST",
          body: JSON.stringify({
            student_id: this.assignForm.student_id,
            fee_type_id: Number(this.assignForm.fee_type_id),
            total_fees_kobo: Math.round(naira * 100),
          }),
        });
        Alpine.store("app").notify("Fee assigned to student.");
        this.assignOpen = false;
        await this.load();
        await this.openDetail(this.assignForm.student_id);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.assignSubmitting = false;
      }
    },

    // --- send a reminder to just this one parent (WhatsApp only) ---
    async remindOne(studentId) {
      if (this.remindingId) return;
      if (!confirm("Send a WhatsApp fee reminder to this parent now?")) return;

      this.remindingId = studentId;
      try {
        // student_id scopes it to one parent; include_payment_link=false → no Paystack link.
        const result = await api(
          `/reminders/send?school_id=${CONFIG.SCHOOL_ID}&student_id=${studentId}&include_payment_link=false`,
          { method: "POST" }
        );
        Alpine.store("app").notify(result.message || "Reminder sent.");
        // If the drawer is open on this student, refresh its message history.
        if (this.detail && this.detail.student_id === studentId) {
          await this.openDetail(studentId);
        }
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.remindingId = null;
      }
    },

    activityIcon,
    timeAgo,
    formatDateTime,
  }));

  // -- Setup screen: manage the school's fee-type catalog ---------------------
  // Fee TYPES are the templates (e.g. "Tuition — First Term", ₦75,000). Assigning
  // one to a student creates a fee RECORD (handled on the Parents screen). This
  // screen is where staff define and review those templates.
  Alpine.data("setup", () => ({
    loading: true,
    feeTypes: [],

    // fee categories (the master list)
    catLoading: true,
    categories: [],

    // add-category form
    categoryOpen: false,
    categorySubmitting: false,
    categoryForm: { name: "" },

    // create-fee-type form
    createOpen: false,
    createSubmitting: false,
    createForm: { category_id: "", section: "Primary", term: "", amount_naira: "" },

    async init() {
      await Promise.all([this.load(), this.loadCategories()]);
    },

    async load() {
      this.loading = true;
      try {
        this.feeTypes = await api(`/fees/types?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async loadCategories() {
      this.catLoading = true;
      try {
        this.categories = await api(`/fees/categories?school_id=${CONFIG.SCHOOL_ID}`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.catLoading = false;
      }
    },

    // --- categories ---
    openCategory() {
      this.categoryForm = { name: "" };
      this.categoryOpen = true;
    },

    closeCategory() {
      this.categoryOpen = false;
    },

    async submitCategory() {
      if (this.categorySubmitting) return;
      if (!this.categoryForm.name.trim()) {
        Alpine.store("app").notify("Enter a category name.", "error");
        return;
      }
      this.categorySubmitting = true;
      try {
        await api(`/fees/categories`, {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            name: this.categoryForm.name.trim(),
          }),
        });
        Alpine.store("app").notify("Category added.");
        this.categoryOpen = false;
        await this.loadCategories();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.categorySubmitting = false;
      }
    },

    async deleteCategory(cat) {
      if (!confirm(`Delete the "${cat.name}" category? This can't be undone.`)) return;
      try {
        await api(`/fees/categories/${cat.id}`, { method: "DELETE" });
        Alpine.store("app").notify("Category deleted.");
        await this.loadCategories();
      } catch (e) {
        // The backend refuses if any fee type still uses it — show that reason.
        Alpine.store("app").notify(e.message, "error");
      }
    },

    // --- fee types ---
    openCreate() {
      if (this.categories.length === 0) {
        Alpine.store("app").notify("Add a fee category first.", "error");
        return;
      }
      this.createForm = { category_id: "", section: "Primary", term: "", amount_naira: "" };
      this.createOpen = true;
    },

    closeCreate() {
      this.createOpen = false;
    },

    async submitCreate() {
      if (this.createSubmitting) return;
      if (!this.createForm.category_id) {
        Alpine.store("app").notify("Choose a category.", "error");
        return;
      }
      if (!this.createForm.section) {
        Alpine.store("app").notify("Choose a section.", "error");
        return;
      }
      if (!this.createForm.term.trim()) {
        Alpine.store("app").notify("Enter the term (e.g. First Term).", "error");
        return;
      }
      const naira = parseFloat(this.createForm.amount_naira);
      if (!naira || naira <= 0) {
        Alpine.store("app").notify("Enter a valid default amount.", "error");
        return;
      }

      this.createSubmitting = true;
      try {
        await api(`/fees/types`, {
          method: "POST",
          body: JSON.stringify({
            school_id: CONFIG.SCHOOL_ID,
            category_id: Number(this.createForm.category_id),
            section: this.createForm.section,
            term: this.createForm.term.trim(),
            amount_kobo: Math.round(naira * 100),
          }),
        });
        Alpine.store("app").notify("Fee type created.");
        this.createOpen = false;
        await this.load();
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.createSubmitting = false;
      }
    },

    async deleteFeeType(t) {
      if (!confirm(`Delete "${t.name} · ${t.section} · ${t.term}"?`)) return;
      try {
        await api(`/fees/types/${t.id}`, { method: "DELETE" });
        Alpine.store("app").notify("Fee type deleted.");
        await this.load();
      } catch (e) {
        // Refused if any student has it assigned — show that reason.
        Alpine.store("app").notify(e.message, "error");
      }
    },

    nairaFromKobo,
  }));

  // -- Activity screen --------------------------------------------------------
  Alpine.data("activity", () => ({
    loading: true,
    items: [],

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        this.items = await api(`/activity/?school_id=${CONFIG.SCHOOL_ID}&limit=100`);
      } catch (e) {
        Alpine.store("app").notify(e.message, "error");
      } finally {
        this.loading = false;
      }
    },

    activityIcon,
    timeAgo,
    formatDateTime,
  }));
});
