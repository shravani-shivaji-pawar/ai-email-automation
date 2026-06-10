import json
import re
import time
import html
from typing import Any
from streamlit_autorefresh import st_autorefresh
import requests
import streamlit as st

# ════════════════════════════════════════════
# CONFIG & STYLES (from app2.py)
# ════════════════════════════════════════════
st.set_page_config(page_title="AI Email Automation Agent", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f8faff 0%, #eef3ff 100%);
    }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    h1, h2, h3 {
        letter-spacing: -0.02em;
    }
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e6ebf5;
        border-radius: 14px;
        padding: 0.6rem 0.8rem;
        box-shadow: 0 6px 20px rgba(24, 39, 75, 0.05);
    }
    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea {
        border-radius: 10px !important;
    }
    div[data-testid="stFileUploader"] section {
        border-radius: 12px;
        border: 1px dashed #b8c7f0;
        background: #fbfcff;
    }
    div.stButton > button {
        border-radius: 10px;
        border: 1px solid #d8def0;
        padding: 0.45rem 0.9rem;
        font-weight: 600;
    }
    .hero {
        background: linear-gradient(135deg, #304ffe 0%, #5e7bff 100%);
        color: white;
        border-radius: 16px;
        padding: 1.05rem 1.15rem;
        margin: 0.4rem 0 1.1rem 0;
        box-shadow: 0 12px 30px rgba(48, 79, 254, 0.25);
    }
    .hero p {
        margin: 0.3rem 0 0 0;
        opacity: 0.92;
        font-size: 0.96rem;
    }
    .live-badge {
        display: inline-block;
        background: #ff4b4b;
        color: white;
        border-radius: 6px;
        padding: 2px 10px;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        animation: pulse 1s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    .preview-rect {
        background: #ffffff;
        border: 1px solid #e6ebf5;
        border-radius: 12px;
        padding: 0.9rem;
        margin-bottom: 0.8rem;
    }
    .preview-body {
        border: 1px solid #dce3f4;
        border-radius: 10px;
        background: #f8faff;
        padding: 0.85rem;
        max-height: 260px;
        overflow-y: auto;
        overflow-x: hidden;
        white-space: pre-wrap;
        word-break: break-word;
        overflow-wrap: anywhere;
        line-height: 1.45;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ════════════════════════════════════════════
# SESSION STATE
# ════════════════════════════════════════════
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "message" not in st.session_state:
    st.session_state.message = ""
if "preview" not in st.session_state:
    st.session_state.preview = []
if "manual_mode" not in st.session_state:
    st.session_state.manual_mode = False
if "last_excel_name" not in st.session_state:
    st.session_state.last_excel_name = ""
if "attachments_uploaded" not in st.session_state:
    st.session_state.attachments_uploaded = []
if "send_started" not in st.session_state:
    st.session_state.send_started = False
if "manual_initialized" not in st.session_state:
    st.session_state.manual_initialized = False
if "manual_current" not in st.session_state:
    st.session_state.manual_current = None
if "manual_contacts" not in st.session_state:
    st.session_state.manual_contacts = []
if "show_form" not in st.session_state:
    st.session_state.show_form = False
if "insights_question" not in st.session_state:
    st.session_state.insights_question = ""
if "insights_answer" not in st.session_state:
    st.session_state.insights_answer = ""
if "insights_meta" not in st.session_state:
    st.session_state.insights_meta = {}
if "insights_history" not in st.session_state:
    st.session_state.insights_history = []
if "insights_use_memory" not in st.session_state:
    st.session_state.insights_use_memory = False
if "insights_recent_emails" not in st.session_state:
    st.session_state.insights_recent_emails = []
if "insights_selected_uid" not in st.session_state:
    st.session_state.insights_selected_uid = ""


# ════════════════════════════════════════════
# API HELPERS
# ════════════════════════════════════════════
def api_base_url() -> str:
    return st.session_state.get("api_base_url", "http://127.0.0.1:8000")


def get_json(endpoint: str) -> dict[str, Any] | None:
    try:
        res = requests.get(f"{api_base_url()}{endpoint}", timeout=20)
        if res.status_code >= 400:
            return None
        return res.json()
    except Exception:
        return None


def post_json(endpoint: str, payload: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    try:
        # One quick retry to absorb transient backend/IMAP delays.
        try:
            res = requests.post(f"{api_base_url()}{endpoint}", json=payload, timeout=timeout)
        except requests.exceptions.Timeout:
            res = requests.post(f"{api_base_url()}{endpoint}", json=payload, timeout=timeout + 30)
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            "Backend request timed out. Please wait a bit and try again, "
            "or increase backend responsiveness."
        ) from exc

    data = res.json()
    if res.status_code >= 400:
        raise RuntimeError(data.get("detail", "Request failed"))
    return data


# ════════════════════════════════════════════
# AUTH UI (from shravani's app.py)
# ════════════════════════════════════════════
def auth_ui():
    st.markdown(
        """
        <div class="hero">
          <h3 style="margin:0;">🔐 AI Email Automation System</h3>
          <p>Sign in or create an account to access your personalized email workspace.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        st.subheader("Login")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pass")

        if st.button("Login", use_container_width=True):
            if not email or not password:
                st.error("Enter email and password")
            else:
                try:
                    res = post_json("/api/login", {"email": email, "password": password})
                    st.session_state.logged_in = True
                    st.session_state.user_role = res["role"]
                    st.session_state.user_id = res["user_id"]
                    st.success("Login successful")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with tab2:
        st.subheader("Create Account")
        name = st.text_input("Full Name", key="reg_name")
        email = st.text_input("Email", key="reg_email")
        phone = st.text_input("Phone", key="reg_phone")
        role = st.radio("Account Type", ["individual", "organizational"], horizontal=True)
        password = ""
        app_password = ""

        if role == "individual":
            st.info("For individual account, use Gmail App Password for sending emails.")
            st.markdown("[Generate App Password](https://myaccount.google.com/apppasswords)")
            st.markdown("[How to generate App Password (YouTube)](https://www.youtube.com/results?search_query=gmail+app+password+generate)")
            app_password = st.text_input("App Password", type="password", key="reg_app_pass")
        else:
            password = st.text_input("Password", type="password", key="reg_pass")

        if st.button("Register", use_container_width=True):
            if len(name.strip()) < 3:
                st.error("Name must be at least 3 characters")
            elif not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
                st.error("Enter a valid email")
            elif not phone.isdigit() or len(phone) != 10:
                st.error("Phone must be 10 digits")
            elif role == "organizational" and len(password) < 6:
                st.error("Password must be at least 6 characters")
            elif role == "individual" and len(app_password.replace(" ", "")) != 16:
                st.error("App password must be 16 letters")
            else:
                try:
                    payload = {
                        "name": name,
                        "email": email,
                        "phone": phone,
                        "password": password,
                        "role": role,
                    }
                    if role == "individual":
                        payload["app_password"] = app_password

                    res = post_json(
                        "/api/register",
                        payload,
                    )
                    st.success(res["message"])
                except Exception as e:
                    st.error(str(e))


# ════════════════════════════════════════════
# ORGANIZATIONAL DASHBOARD (from shravani + app2.py UI)
# ════════════════════════════════════════════
def organizational_dashboard():
    st.markdown(
        """
        <div class="hero">
          <h3 style="margin:0;">🏢 Organizational Panel</h3>
          <p>Manage your senders, run campaigns, and monitor delivery from one place.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("📂 Navigation")
        page = st.radio("Go to", ["📊 Dashboard", "🤖 AI Agent", "💬 Prompt Area"])
        st.divider()

        try:
            res = requests.get(f"{api_base_url()}/api/senders/{st.session_state.user_id}", timeout=10)
            senders = res.json().get("senders", [])
        except Exception:
            senders = []

        st.subheader("📧 Senders")
        if not senders:
            st.info("No senders yet")
        else:
            for sender in senders:
                if st.button(sender["email"], key=f"sidebar_sender_{sender['id']}"):
                    requests.post(
                        f"{api_base_url()}/api/senders/select",
                        json={"sender_id": sender["id"]},
                    )
                    st.session_state.active_email = sender["email"]
                    st.rerun()

        st.divider()
        st.caption(f"Signed in as **{st.session_state.user_role}**")
        if st.button("🚪 Logout"):
            for key in ["logged_in", "user_role", "user_id", "active_email"]:
                st.session_state.pop(key, None)
            st.rerun()

    if "active_email" in st.session_state:
        st.success(f"✅ Active Sender: {st.session_state.active_email}")
    else:
        st.warning("⚠️ No sender selected — pick one from the sidebar")

    st.divider()

    if page == "📊 Dashboard":
        col1, col2 = st.columns([6, 1])
        with col1:
            st.subheader("📊 Organizational Dashboard")
        with col2:
            if st.button("➕ Add Email"):
                st.session_state.show_form = not st.session_state.get("show_form", False)

        st.divider()

        if st.session_state.get("show_form"):
            with st.container(border=True):
                st.markdown("### ➕ Add New Sender")
                c1, c2 = st.columns(2)
                with c1:
                    s_name = st.text_input("👤 Name", key="new_sender_name")
                    s_org = st.text_input("🏢 Organization", key="new_sender_org")
                with c2:
                    s_email = st.text_input("📧 Email", key="new_sender_email")
                    s_password = st.text_input("🔑 App Password", type="password", key="new_sender_pass")

                st.markdown("[🔗 Generate App Password](https://myaccount.google.com/apppasswords)")

                colA, colB = st.columns(2)
                with colA:
                    if st.button("Save Sender", use_container_width=True):
                        res = requests.post(
                            f"{api_base_url()}/api/senders/add",
                            json={
                                "user_id": st.session_state.user_id,
                                "name": s_name,
                                "organization_name": s_org,
                                "email": s_email,
                                "password": s_password,
                            },
                        )
                        if res.status_code == 200:
                            st.success("Sender Added")
                            st.session_state.show_form = False
                            st.rerun()
                        else:
                            st.error("Failed to add sender")
                with colB:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state.show_form = False
                        st.rerun()

            st.divider()

        st.subheader("📬 Sender List")
        if not senders:
            st.info("No senders added yet. Click **➕ Add Email** to get started.")
        else:
            for sender in senders:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.markdown(
                            f"**📧 {sender['email']}**  \n"
                            f"👤 {sender.get('name', '-')}  \n"
                            f"🏢 {sender.get('organization_name', '-')}"
                        )
                    with c2:
                        if st.button("Select", key=f"sel_{sender['id']}", use_container_width=True):
                            requests.post(
                                f"{api_base_url()}/api/senders/select",
                                json={"sender_id": sender["id"]},
                            )
                            st.session_state.active_email = sender["email"]
                            st.rerun()

    elif page == "🤖 AI Agent":
        if "active_email" not in st.session_state:
            st.error("⚠️ Please select a sender from the sidebar first.")
            st.stop()

        _agent_page()
    elif page == "💬 Prompt Area":
        if "active_email" not in st.session_state:
            st.error("⚠️ Please select a sender from the sidebar first.")
            st.stop()
        _prompt_area_page()


# ════════════════════════════════════════════
# INDIVIDUAL DASHBOARD
# ════════════════════════════════════════════
def individual_dashboard():
    with st.container():
        col1, col2 = st.columns([8, 2])

        with col1:
            st.markdown("""
                <div class="hero">
                    <h3 style="margin:0;">📧 AI Email Assistant</h3>
                    <p>Create and send personalized outreach emails in a few guided steps.</p>
                </div>
            """, unsafe_allow_html=True)

        with col2:
            st.write("")  # spacer
            st.write("")  # adjust this
            if st.button("🚪 Logout"):
                for key in ["logged_in", "user_role", "user_id"]:
                    st.session_state.pop(key, None)
                st.rerun()


    _agent_page()


# ════════════════════════════════════════════
# SHARED AGENT PAGE (from app2.py — modern UI)
# ════════════════════════════════════════════
def _agent_page():
    
    st.subheader("🤖 AI Email Agent")
    # ── Live send progress ──────────────────────────────────────────────
    st_autorefresh(interval=2000, key="send_status_refresh")
    send_status = get_json("/api/send-status")
    in_progress = send_status and send_status.get("send_in_progress", False)

       
    if in_progress:
        prog = send_status.get("progress", {})
        total = prog.get("total", 1) or 1
        processed = prog.get("processed", 0)
        fraction = processed / total

        st.markdown('<span class="live-badge">● SENDING LIVE</span>', unsafe_allow_html=True)
        summary = prog.get("current_emails_summary") or prog.get("current_email")
        st.markdown(f"**Currently sending (combined):** `{summary or '…'}`")
        if prog.get("active_job_count", 0) > 1:
            st.caption(f"{int(prog.get('active_job_count', 1))} concurrent send job(s)")

        p1, p2, p3, p4, p5, p6 = st.columns(6)
        p1.metric("Total", prog.get("total", 0))
        p2.metric("Processed", processed)
        p3.metric("Delivered", prog.get("delivered", 0))
        p4.metric("Failed", prog.get("failed", 0))
        p5.metric("Skipped", prog.get("skipped", 0))
        p6.metric("Bounced", prog.get("bounced", 0))
        st.progress(fraction, text=f"{processed}/{total} emails processed (all active jobs)")

        active_jobs = [
            j for j in (send_status.get("jobs") or []) if j.get("in_progress")
        ]
        if active_jobs:
            with st.expander("Per-sender job progress", expanded=True):
                for j in active_jobs:
                    p = j.get("progress") or {}
                    jt = int(p.get("total") or 0) or 1
                    jp = int(p.get("processed") or 0)
                    st.markdown(
                        f"**{j.get('from_email', '?')}** · "
                        f"job `{j.get('job_id', '')}` · "
                        f"{jp}/{jt} · "
                        f"✅ {p.get('delivered',0)} delivered · "
                        f"❌ {p.get('failed',0)} failed · "
                        f"📩 {p.get('bounced',0)} bounced · "
                        f"now `{p.get('current_email', '—')}`"
                   )
                    st.progress(jp / jt, text=f"{jp}/{jt}")

        st.error("⚠️ One or more send jobs are in progress.")
        if st.button("🛑 EMERGENCY STOP", type="primary", use_container_width=True):
            try:
                post_json("/api/stop", {})
                st.warning("Stop signal sent — will halt after the current email.")
            except Exception as e:
                st.error(str(e))

        st.caption("🔄 Refresh page to update live progress.")
        

    elif send_status and send_status.get("success"):
        last = send_status.get("last_batch") or {}
        if last:
            st.subheader("Delivery Snapshot")
            c1, c2, c3 = st.columns(3)
            c1.metric("Total", last.get("total", 0))
            c2.metric("Delivered", last.get("delivered", 0))
            c3.metric("Bounced", last.get("bounced", 0))
            if last.get("total"):
                st.progress(last.get("delivered", 0) / last.get("total", 1))
            with st.expander("See full batch details"):
                st.json(last)
    else:
        st.warning("Backend not connected. Start FastAPI and verify the backend URL.")

    st.divider()
    st.info(
        "Quick flow: Upload contacts → Write message → Preview → Send. "
        "Use {first_name} in your message for personalization."
    )

    left_col, right_col = st.columns(2)

    # ── LEFT: Contacts & Attachments ───────────────────────────────────
    with left_col:
        with st.container(border=True):
            st.subheader("Step 1: Upload Contact File")
            file = st.file_uploader(
                "Contacts Excel file",
                type=["xlsx", "xls"],
                help="Include at least an email column and optionally first names.",
            )
            if st.button("Upload contacts", use_container_width=True):
                if not file:
                    st.warning("Please choose an Excel file first.")
                else:
                    try:
                        with st.spinner("Uploading contacts..."):
                            res = requests.post(
                                f"{api_base_url()}/api/upload-excel",
                                files={"file": (file.name, file.getvalue())},
                            )
                            data = res.json()
                            st.session_state.last_excel_name = file.name
                            st.success(f"Uploaded {data['rows_count']} contacts from {file.name}.")
                    except Exception as e:
                        st.error(str(e))
            if st.session_state.last_excel_name:
                st.caption(f"Current contact file: {st.session_state.last_excel_name}")

        with st.container(border=True):
            st.subheader("Step 2: Add Attachments (Optional)")
            files = st.file_uploader(
                "Choose attachment files",
                accept_multiple_files=True,
                help="Attach brochures, PDFs, or other files sent with each email.",
            )
            if st.button("Save attachments", use_container_width=True):
                if files:
                    try:
                        with st.spinner("Uploading attachments..."):
                            req_files = [("files", (f.name, f.getvalue())) for f in files]
                            requests.post(f"{api_base_url()}/api/upload-attachments", files=req_files)
                            st.session_state.attachments_uploaded = [f.name for f in files]
                            st.success(f"Saved {len(files)} attachment(s).")
                    except Exception as e:
                        st.error(str(e))
                else:
                    st.info("No attachments selected. You can skip this step.")
            if st.session_state.attachments_uploaded:
                st.caption("Saved attachments: " + ", ".join(st.session_state.attachments_uploaded))

    # ── RIGHT: Message ─────────────────────────────────────────────────
    with right_col:
        with st.container(border=True):
            st.subheader("Step 3: Prepare Your Email")
            objective = st.text_input(
                "What is the goal of this campaign?",
                placeholder="Example: Introduce our AI support service and book a 15-minute call.",
            )
            subject = st.text_input("Email subject", placeholder="Example: Quick idea for your team")
            c1, c2, c3 = st.columns(3)

            with c1:
                if st.button("Draft message"):
                    data = post_json(
                        "/api/generate-message",
                        {"objective": objective},
                    )
                    st.session_state.message = data["message"]
                    st.rerun()

            with c2:
                if st.button("Improve tone"):
                    data = post_json(
                        "/api/enhance-message",
                        {"message": st.session_state.message},
                    )

                    st.session_state.message = data["message"]
                    st.rerun()

            with c3:
                if st.button("Preview first 5"):
                    data = post_json(
                        "/api/preview",
                        {
                            "message_template": st.session_state.message,
                            "limit": 5,
                        },
                    )
                    st.session_state.preview = data["previews"]

            # st.session_state.message = st.text_area(
            #     "Email message",
            #     value=st.session_state.message,
            #     key="message_box",
            #     height=220,
            # )
            

            st.session_state.message = st.text_area(
                "Email message",
                value=st.session_state.get("message", ""),
                height=220,
                key="message_box_widget",
                help="Tip: keep it short and clear. Use {first_name} to personalize each email.",

            )

            # st.session_state.message = st.session_state.message_box
    # ── Send mode ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("Step 4: Choose Sending Mode")
        mode = st.radio(
            "How would you like to send?",
            ["Auto", "Manual"],
            horizontal=True,
            help="Auto sends all emails in one go. Manual lets you review one by one.",
        )
        st.session_state.manual_mode = mode == "Manual"

    # ── Send actions ───────────────────────────────────────────────────
    if not st.session_state.manual_mode:
        # Multiple org senders may run concurrent batches — do not block Send.
        send_disabled = False
        if st.button(
            "Send all emails",
            type="primary",
            use_container_width=True,
            disabled=send_disabled,
        ):
            try:
                data = post_json(
                    "/api/send",
                    {"subject": subject, "message_template": st.session_state.message},
                )
                st.success(data["message"])
                st.session_state.send_started = True
                time.sleep(1)
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))

        if in_progress:
            st.info("Send jobs are running; you can queue another batch after selecting a sender and uploading contacts.")

    else:
        with st.container(border=True):
            st.subheader("📋 Manual Send Mode")

            init_col, reinit_col = st.columns([3, 1])
            with init_col:
                st.caption("Load your contact list to start browsing and sending one by one.")
            with reinit_col:
                if st.button("🔄 Load / Reload contacts", use_container_width=True):
                    try:
                        resp = post_json(
                            "/api/manual/init",
                            {"subject": subject, "message_template": st.session_state.message},
                        )
                        st.session_state.manual_initialized = True
                        peek = get_json("/api/manual/peek?index=0")
                        st.session_state.manual_current = peek
                        contacts_data = get_json("/api/manual/list")
                        st.session_state.manual_contacts = contacts_data.get("contacts", []) if contacts_data else []
                        st.success(f"Loaded {resp.get('total', 0)} contacts.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

            if not st.session_state.manual_initialized:
                st.info("Click **Load / Reload contacts** above to begin manual mode.")
            else:
                contacts = st.session_state.manual_contacts
                total = len(contacts)
                current = st.session_state.manual_current or {}
                current_idx = current.get("index", 0)
                current_status = current.get("status", "pending")

                sent_count = sum(1 for c in contacts if c["status"] == "sent")
                skipped_count = sum(1 for c in contacts if c["status"] == "skipped")
                st.progress(
                    (sent_count + skipped_count) / total if total else 0,
                    text=f"{sent_count} sent · {skipped_count} skipped · {total - sent_count - skipped_count} pending  ({current_idx + 1} of {total})",
                )

                status_colors = {"sent": "🟢", "skipped": "🟡", "pending": "🔵"}
                status_icon = status_colors.get(current_status, "⚪")

                st.markdown(
                    f"""
                    <div style="
                        background:#f0f4ff;
                        border:1.5px solid #c7d4f7;
                        border-radius:14px;
                        padding:1rem 1.2rem;
                        margin:0.5rem 0 0.8rem 0;
                    ">
                        <div style="font-size:0.78rem;color:#6b7caa;margin-bottom:4px;">
                            Contact {current_idx + 1} of {total} &nbsp;·&nbsp; {status_icon} {current_status.upper()}
                        </div>
                        <div style="font-size:1.3rem;font-weight:700;color:#1a237e;letter-spacing:-0.01em;">
                            ✉️ &nbsp;{current.get('to', '—')}
                        </div>
                        <div style="font-size:0.9rem;color:#374151;margin-top:4px;">
                            <b>Subject:</b> {current.get('subject', '—')}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                with st.expander("📄 Preview email body", expanded=True):
                    st.code(current.get("body", ""), language="")

                nav1, nav2, nav3, nav4 = st.columns([1, 1, 1.5, 1])

                with nav1:
                    if st.button("◀ Previous", use_container_width=True, disabled=current_idx == 0):
                        peek = post_json("/api/manual/go-prev", {})
                        st.session_state.manual_current = peek
                        contacts_data = get_json("/api/manual/list")
                        st.session_state.manual_contacts = contacts_data.get("contacts", []) if contacts_data else []
                        st.rerun()

                with nav2:
                    if st.button("Next ▶", use_container_width=True, disabled=current_idx >= total - 1):
                        peek = post_json("/api/manual/go-next", {})
                        st.session_state.manual_current = peek
                        contacts_data = get_json("/api/manual/list")
                        st.session_state.manual_contacts = contacts_data.get("contacts", []) if contacts_data else []
                        st.rerun()

                with nav3:
                    already_sent = current_status == "sent"
                    if st.button(
                        "✅ Send this email" if not already_sent else "✅ Already sent",
                        type="primary",
                        use_container_width=True,
                        disabled=already_sent,
                    ):
                        try:
                            result = post_json(
                                "/api/manual/send",
                                {"subject": subject, "message_template": st.session_state.message},
                            )
                            st.success(f"Sent → {result.get('to', current.get('to'))}")
                            if current_idx < total - 1:
                                peek = get_json(f"/api/manual/peek?index={current_idx + 1}")
                                st.session_state.manual_current = peek
                            contacts_data = get_json("/api/manual/list")
                            st.session_state.manual_contacts = contacts_data.get("contacts", []) if contacts_data else []
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

                with nav4:
                    jump_idx = st.number_input(
                        "Jump to #", min_value=1, max_value=total, value=current_idx + 1,
                        label_visibility="collapsed",
                    )
                    if st.button("Go", use_container_width=True):
                        peek = get_json(f"/api/manual/peek?index={int(jump_idx) - 1}")
                        st.session_state.manual_current = peek
                        st.rerun()

                with st.expander(f"👥 All contacts ({total})", expanded=False):
                    contacts_data = get_json("/api/manual/list")
                    if contacts_data:
                        contacts = contacts_data.get("contacts", [])
                        st.session_state.manual_contacts = contacts
                    for c in contacts:
                        icon = {"sent": "🟢", "skipped": "🟡", "pending": "🔵"}.get(c["status"], "⚪")
                        is_cur = "**→**" if c["is_current"] else "&nbsp;&nbsp;&nbsp;"
                        st.markdown(
                            f"{is_cur} `#{c['index']+1}` &nbsp; {icon} &nbsp; `{c['to']}` &nbsp; *{c['status']}*",
                            unsafe_allow_html=True,
                        )


    # ── Preview output ─────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("Step 5: Message Preview")
        if not st.session_state.preview:
            st.info("No preview yet. Click 'Preview first 5' to review your personalized emails.")
        else:
            for i, item in enumerate(st.session_state.preview, 1):
                message_text = html.escape(item.get("message", ""))
                st.markdown(
                    f"""
                    <div class="preview-rect">
                        <div style="font-weight:600; margin-bottom:0.55rem;">Recipient {i}</div>
                        <div class="preview-body">{message_text}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def _prompt_area_page():
    st.subheader("💬 Prompt Area (Inbox Assistant)")

    # Ensure defaults
    if "insights_history" not in st.session_state:
        st.session_state.insights_history = []
    if "insights_history_loaded" not in st.session_state:
        st.session_state.insights_history_loaded = False
    if "insights_selected_uid" not in st.session_state:
        st.session_state.insights_selected_uid = ""
    if "insights_full_email" not in st.session_state:
        st.session_state.insights_full_email = ""
    if "insights_semantic_query" not in st.session_state:
        st.session_state.insights_semantic_query = ""
    if "insights_semantic_hits" not in st.session_state:
        st.session_state.insights_semantic_hits = []
    if "bulk_candidates" not in st.session_state:
        st.session_state.bulk_candidates = []
    if "prompt_last_question" not in st.session_state:
        st.session_state.prompt_last_question = ""
    if "prompt_last_answer" not in st.session_state:
        st.session_state.prompt_last_answer = ""
    if "prompt_scan_unlimited" not in st.session_state:
        st.session_state.prompt_scan_unlimited = False
    if "prompt_scan_max" not in st.session_state:
        st.session_state.prompt_scan_max = 200

    # Load persisted history once per session for the active sender.
    if not st.session_state.insights_history_loaded:
        try:
            hist = get_json(f"/api/chat/history?user_id={int(st.session_state.user_id)}&limit=80")
            if hist and hist.get("history"):
                st.session_state.insights_history = hist["history"]
        except Exception:
            pass
        st.session_state.insights_history_loaded = True

    left, right = st.columns([1.6, 1], gap="large")

    with right:
        with st.container(border=True):
            st.subheader("⚡ Index & Search")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Fast index (headers)", use_container_width=True):
                    try:
                        with st.spinner("Indexing headers..."):
                            res = post_json("/api/email-insights/index?mode=headers&limit=400", {}, timeout=180)
                        st.success(f"Indexed {res.get('indexed', 0)} · Updated {res.get('updated', 0)}")
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("Deep index (full bodies)", use_container_width=True):
                    try:
                        with st.spinner("Indexing full bodies (slower, but best search)..."):
                            res = post_json("/api/email-insights/index?mode=full&limit=250", {}, timeout=300)
                        st.success(f"Indexed {res.get('indexed', 0)} · Updated {res.get('updated', 0)}")
                    except Exception as e:
                        st.error(str(e))

            st.session_state.insights_semantic_query = st.text_input(
                "Semantic search",
                value=st.session_state.insights_semantic_query,
                placeholder="Search like: 'invoice', 'meeting reschedule', 'project update'...",
            )
            if st.button("Search", type="primary", use_container_width=True):
                try:
                    res = get_json(
                        f"/api/email-insights/search?q={requests.utils.quote(st.session_state.insights_semantic_query)}&top_k=15"
                    )
                    st.session_state.insights_semantic_hits = (res or {}).get("hits", [])
                except Exception as e:
                    st.error(str(e))

            hits = st.session_state.insights_semantic_hits or []
            if hits:
                options = [
                    f"UID {h.get('uid','')} | score {h.get('score',0):.3f} | {((h.get('meta') or {}).get('subject')) or '(no subject)'}"
                    for h in hits
                ]
                pick = st.selectbox("Top matches", list(range(len(options))), format_func=lambda i: options[i])
                picked = hits[int(pick)]
                st.session_state.insights_selected_uid = picked.get("uid", "")

        with st.container(border=True):
            st.subheader("📩 Selected Email")
            uid = st.text_input("UID", value=st.session_state.insights_selected_uid).strip()
            st.session_state.insights_selected_uid = uid
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Fetch full email", type="primary", use_container_width=True, disabled=not bool(uid)):
                    try:
                        with st.spinner("Fetching full email..."):
                            data = get_json(f"/api/email/uid/{uid}")
                        body = (data or {}).get("body", "")
                        st.session_state.insights_full_email = body
                        # Lazy: once full is fetched, upgrade the embedding for that UID in the background index via deep index later.
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("Clear", use_container_width=True):
                    st.session_state.insights_full_email = ""

            if st.session_state.insights_full_email:
                st.code(st.session_state.insights_full_email, language="")

        with st.container(border=True):
            st.subheader("✅ Actions")
            action = st.selectbox(
                "Single action",
                ["mark_read", "mark_unread", "mark_important", "move_to_trash", "move_to_spam", "unsubscribe"],
            )
            if st.button("Run single action", use_container_width=True, disabled=not bool(uid)):
                try:
                    with st.spinner("Applying action..."):
                        res = post_json("/api/email-insights/action", {"action": action, "uid": uid}, timeout=30)
                    st.success(res.get("message", "Action completed."))
                except Exception as e:
                    st.error(str(e))

    with left:
        with st.container(border=True):
            st.subheader("💬 Chat")
            st.caption("Ask one question at a time. The latest answer stays below until your next question.")

            c1, c2 = st.columns([1, 1])
            with c1:
                st.session_state.prompt_scan_unlimited = st.checkbox(
                    "Unlimited scan",
                    value=st.session_state.prompt_scan_unlimited,
                    help="More thorough but slower. Uses safety limits to avoid timeouts.",
                )
            with c2:
                if not st.session_state.prompt_scan_unlimited:
                    st.session_state.prompt_scan_max = st.number_input(
                        "Emails to scan",
                        min_value=20,
                        max_value=1500,
                        value=int(st.session_state.prompt_scan_max),
                        step=20,
                        help="Lower is faster; higher is more thorough.",
                    )

        prompt = st.chat_input("Ask about your emails or request actions…")
        if prompt:
            user_text = prompt.strip()
            st.session_state.prompt_last_question = user_text
            # Keep in-memory history updated (used for AI memory + UI history at bottom).
            st.session_state.insights_history.append({"role": "user", "content": user_text})
            try:
                post_json(
                    "/api/chat/turn",
                    {"user_id": int(st.session_state.user_id), "role": "user", "content": user_text},
                    timeout=10,
                )
            except Exception:
                pass

            try:
                with st.spinner("Thinking..."):
                    max_emails = 0 if st.session_state.prompt_scan_unlimited else int(st.session_state.prompt_scan_max)
                    res = post_json(
                        "/api/email-insights/query",
                        {
                            "question": user_text,
                            "max_emails": max_emails,
                            "use_memory": True,
                            "history": st.session_state.insights_history[-24:],
                        },
                        timeout=180 if max_emails == 0 else 75,
                    )
                answer = (res or {}).get("answer", "")
            except Exception as e:
                answer = f"Error: {str(e)}"

            st.session_state.prompt_last_answer = answer
            st.session_state.insights_history.append({"role": "assistant", "content": answer})
            try:
                post_json(
                    "/api/chat/turn",
                    {"user_id": int(st.session_state.user_id), "role": "assistant", "content": answer},
                    timeout=10,
                )
            except Exception:
                pass
            st.rerun()

        if st.session_state.prompt_last_answer:
            with st.container(border=True):
                if st.session_state.prompt_last_question:
                    st.markdown(f"**Question:** {st.session_state.prompt_last_question}")
                st.markdown(st.session_state.prompt_last_answer)

        # Full history lives at the bottom (only when user clicks).
        st.divider()
        show_history = st.toggle("Show full chat history", value=False)
        if show_history:
            with st.container(border=True):
                st.subheader("🧾 Full Chat History")
                try:
                    hist = get_json(f"/api/chat/history?user_id={int(st.session_state.user_id)}&limit=200")
                    turns = (hist or {}).get("history", []) or []
                except Exception:
                    turns = []
                if not turns:
                    st.info("No saved history found yet.")
                for turn in turns[-200:]:
                    role = (turn.get("role") or "assistant").strip().lower()
                    who = "You" if role == "user" else "Assistant"
                    st.markdown(f"**{who}:** {turn.get('content','')}")


# ════════════════════════════════════════════
# LOGIN GATE & ROLE-BASED ROUTING
# ════════════════════════════════════════════
if not st.session_state.logged_in:
    auth_ui()
    st.stop()

if st.session_state.user_role == "organizational":
    organizational_dashboard()
else:
    individual_dashboard()
