import os
import io
import json
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from hardware_extended import get_hardware_info, get_top_processes
from assistant import ask_hardware_assistant, new_conversation

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
MODEL = "qwen2.5:1.5b"
OLLAMA_URL = "http://localhost:11434/api/generate"
REQUEST_TIMEOUT = 180
HISTORY_LIMIT = 30

st.set_page_config(
    page_title="Linux Hardware AI Assistant",
    page_icon="💻",
    layout="wide",
)


# ---------------------------------------------------------
# Hardware and AI helpers
# ---------------------------------------------------------
@st.cache_data(ttl=3)
def load_hardware_data():
    """Read current Linux hardware information."""
    return get_hardware_info()


def safe_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def generate_ai_response(question, hardware_data, processes=None):
    """
    Use Groq in the public cloud deployment.
    Use local Ollama when no Groq API key is configured.
    """
    process_list = processes or []

    prompt = f"""
You are a careful Linux Hardware Assistant.

Answer the user's question using ONLY the system snapshot
and process list below.

Never invent hardware specifications, process names, or values.
If requested information is absent, say it is unavailable.
Keep labels and units exact. Use simple English.

Important:
- CPU usage is already a percentage.
- RAM available and disk free space are different metrics.
- Do not confuse GB of RAM with GB of disk.
- The deployed application may inspect a cloud Linux environment,
  not the user's personal laptop.
- Never claim cloud hardware information belongs to the user's laptop.
- Compare numeric RAM percentages when identifying top processes.
- If information is missing, clearly say it is unavailable.

SYSTEM SNAPSHOT:
{json.dumps(hardware_data, indent=2, default=str)}

TOP RUNNING PROCESSES:
{json.dumps(process_list, indent=2, default=str)}

USER QUESTION:
{question}

Give a direct, concise answer.
"""

    # Check whether a Groq API key is configured in Streamlit Secrets.
    try:
        groq_api_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        groq_api_key = ""

    try:
        if groq_api_key:
            # Public cloud deployment: use Groq.
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-oss-120b",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a careful Linux hardware "
                                "assistant. Never invent system information."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    "temperature": 0,
                    "max_completion_tokens": 400,
                    "stream": False,
                },
                timeout=60,
            )

            response.raise_for_status()
            payload = response.json()

            answer = (
                payload.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            if not answer:
                return "Groq returned an empty answer. Please try again."

            return answer

        else:
            # Local development: continue using Ollama.
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_predict": 400,
                    },
                },
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()
            payload = response.json()
            answer = payload.get("response", "").strip()

            return answer or "Ollama returned an empty answer."

    except requests.exceptions.Timeout:
        return "The AI request timed out. Please try again."

    except requests.exceptions.HTTPError as error:
        status = response.status_code

        if status == 401:
            return "Groq authentication failed. Please check the API key in Streamlit Secrets."

        if status == 429:
            return "Groq API rate limit reached. Please wait and try again."

        return f"AI service returned HTTP error {status}: {error}"

    except requests.exceptions.ConnectionError:
        return (
            "Cannot connect to the AI service. "
            "Please check your internet connection or Ollama service."
        )

    except (requests.RequestException, ValueError, KeyError, IndexError) as error:
        return f"AI request error: {error}"

    except Exception as error:
        return f"Unexpected AI error: {error}"

# ---------------------------------------------------------
# Hardware Health
# ---------------------------------------------------------
def usage_health(cpu_percent, ram_percent, disk_percent):

    score = 100
    notes = []

    for label, value in (
        ("CPU", cpu_percent),
        ("RAM", ram_percent),
        ("Root disk", disk_percent),
    ):

        if value >= 95:
            score -= 30
            notes.append(
                f"{label} utilization is critical ({value:.1f}%)."
            )

        elif value >= 85:
            score -= 20
            notes.append(
                f"{label} utilization is high ({value:.1f}%)."
            )

        elif value >= 70:
            score -= 10
            notes.append(
                f"{label} utilization is elevated ({value:.1f}%)."
            )

    score = max(0, score)

    label = (
        "Excellent" if score >= 90 else
        "Good" if score >= 75 else
        "Fair" if score >= 55 else
        "Needs attention"
    )

    if not notes:
        notes.append(
            "CPU, RAM and root-disk utilization are below "
            "the configured warning thresholds."
        )

    return score, label, notes


# ---------------------------------------------------------
# PDF Report
# ---------------------------------------------------------
def make_pdf_report(data, score, health_label, notes, processes):

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
    )

    styles = getSampleStyleSheet()

    story = [
        Paragraph(
            "Linux Hardware AI Assistant - System Report",
            styles["Title"],
        ),
        Paragraph(
            f"Generated: {datetime.now().astimezone().strftime('%d %b %Y, %H:%M:%S %Z')}",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph(
            f"Usage indicator: {score}/100 - {health_label}",
            styles["Heading2"],
        ),
        Paragraph(
            "This is a utilization-based indicator, "
            "not a physical hardware diagnostic.",
            styles["Italic"],
        ),
        Spacer(1, 10),
    ]

    fields = [
        ("CPU", "processor", "Processor"),
        ("CPU", "physical_cores", "Physical cores"),
        ("CPU", "logical_cores", "Logical cores"),
        ("CPU", "cpu_usage", "CPU usage (%)"),
        ("CPU", "frequency_mhz", "Frequency (MHz)"),
        ("Memory", "total_gb", "Total RAM (GB)"),
        ("Memory", "used_gb", "Used RAM (GB)"),
        ("Memory", "available_gb", "Available RAM (GB)"),
        ("Memory", "used_percent", "RAM usage (%)"),
        ("Disk", "total_gb", "Root disk total (GB)"),
        ("Disk", "used_gb", "Root disk used (GB)"),
        ("Disk", "free_gb", "Root disk free (GB)"),
        ("Disk", "used_percent", "Root disk usage (%)"),
    ]

    rows = [["Category", "Metric", "Reading"]]

    for category, key, title in fields:

        section = data.get(
            "cpu" if category == "CPU" else
            "memory" if category == "Memory" else
            "disk",
            {},
        )

        rows.append([
            category,
            title,
            str(section.get(key, "Unavailable")),
        ])

    system = data.get("system", {})

    for key, title in [
        ("system", "Operating system"),
        ("release", "Kernel release"),
        ("hostname", "Hostname"),
        ("architecture", "Architecture"),
        ("uptime", "Uptime"),
    ]:

        rows.append([
            "System",
            title,
            str(system.get(key, "Unavailable")),
        ])

    table = Table(
        rows,
        colWidths=[80, 180, 250],
        repeatRows=1,
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F1F5F9")]),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))

    story.extend([
        Paragraph("System readings", styles["Heading2"]),
        table,
        Spacer(1, 12),
        Paragraph("Utilization observations", styles["Heading2"]),
    ])

    for note in notes:
        story.append(
            Paragraph("• " + note, styles["BodyText"])
        )

    if processes:

        story.extend([
            Spacer(1, 8),
            Paragraph(
                "Top processes by RAM usage",
                styles["Heading2"],
            ),
        ])

        process_rows = [
            ["PID", "Process", "CPU %", "RAM %"]
        ]

        for process in processes[:8]:

            process_rows.append([
                str(process.get("PID", "")),
                str(process.get("Process", ""))[:28],
                str(process.get("CPU (%)", "")),
                str(process.get("RAM (%)", "")),
            ])

        process_table = Table(
            process_rows,
            colWidths=[45, 260, 75, 75],
            repeatRows=1,
        )

        process_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))

        story.append(process_table)

    document.build(story)

    return buffer.getvalue()


# ---------------------------------------------------------
# Session State
# ---------------------------------------------------------
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "assistant_messages" not in st.session_state:
    st.session_state.assistant_messages = new_conversation()

if "cpu_history" not in st.session_state:
    st.session_state.cpu_history = []

if "ram_history" not in st.session_state:
    st.session_state.ram_history = []


# ---------------------------------------------------------
# Load Hardware Snapshot
# ---------------------------------------------------------
try:
    data = load_hardware_data()

except Exception as error:
    st.error(
        f"Unable to retrieve hardware information: {error}"
    )
    st.stop()


cpu = data.get("cpu", {})
memory = data.get("memory", {})
disk = data.get("disk", {})
system = data.get("system", {})
network = data.get("network", {})

cpu_usage = safe_number(cpu.get("cpu_usage"))
ram_percent = safe_number(memory.get("used_percent"))
disk_percent = safe_number(disk.get("used_percent"))

total_ram = safe_number(memory.get("total_gb"))
used_ram = safe_number(memory.get("used_gb"))
available_ram = safe_number(memory.get("available_gb"))

total_disk = safe_number(disk.get("total_gb"))
used_disk = safe_number(disk.get("used_gb"))
free_disk = safe_number(disk.get("free_gb"))

health_score, health_label, health_notes = usage_health(
    cpu_usage,
    ram_percent,
    disk_percent,
)


# ---------------------------------------------------------
# Get Top Processes
# ---------------------------------------------------------
try:
    processes = get_top_processes(10) or []

except Exception:
    processes = []


# ---------------------------------------------------------
# Dashboard UI
# ---------------------------------------------------------
st.title("💻 Linux Hardware AI Assistant")

# Identify whether the app is running on Streamlit Cloud.
try:
    IS_CLOUD = bool(st.secrets.get("GROQ_API_KEY", ""))
except Exception:
    IS_CLOUD = False

if IS_CLOUD:
    st.warning(
        "☁️ CLOUD DEPLOYMENT MODE: The hardware information below "
        "belongs to the Streamlit cloud server, not the visitor's laptop."
    )
    st.caption("AI Backend: Groq Cloud API")
else:
    st.success(
        "💻 LOCAL MODE: Hardware information is collected from "
        "your current Linux environment."
    )
    st.caption("AI Backend: Local Ollama (Qwen 2.5 1.5B)")

st.caption(
    "Last sampled: "
    + datetime.now().astimezone().strftime("%d %b %Y, %H:%M:%S")
)

st.info(
    "Automatic page refresh is disabled so it cannot interrupt "
    "a longer AI answer. Use the refresh button below."
)

if st.button("🔄 Refresh System Information"):

    load_hardware_data.clear()
    st.rerun()


# ---------------------------------------------------------
# System Overview
# ---------------------------------------------------------
st.header("📊 System Overview")

col1, col2, col3, col4 = st.columns(4)

col1.metric("CPU Usage", f"{cpu_usage:.1f}%")
col2.metric("Total RAM", f"{total_ram:.2f} GB")
col3.metric("Free Disk", f"{free_disk:.2f} GB")
col4.metric(
    "Usage Health",
    f"{health_score}/100",
    health_label,
)


# ---------------------------------------------------------
# Memory Information
# ---------------------------------------------------------
st.divider()

st.header("🧠 Memory Information")

col1, col2, col3 = st.columns(3)

col1.metric("Total RAM", f"{total_ram:.2f} GB")
col2.metric("Used RAM", f"{used_ram:.2f} GB")
col3.metric("Available RAM", f"{available_ram:.2f} GB")

st.progress(
    max(0.0, min(ram_percent / 100.0, 1.0))
)

st.caption(f"RAM utilization: {ram_percent:.1f}%")

st.metric(
    "Swap used",
    f"{safe_number(memory.get('swap_used_gb')):.2f} GB",
    f"{safe_number(memory.get('swap_percent')):.1f}% of swap",
)


# ---------------------------------------------------------
# Performance Monitoring
# ---------------------------------------------------------
st.divider()

st.header("📈 Performance Monitoring")

sample_time = datetime.now().strftime("%H:%M:%S")

st.session_state.cpu_history.append({
    "Time": sample_time,
    "CPU Usage (%)": cpu_usage,
})

st.session_state.ram_history.append({
    "Time": sample_time,
    "RAM Usage (%)": ram_percent,
})

st.session_state.cpu_history = (
    st.session_state.cpu_history[-HISTORY_LIMIT:]
)

st.session_state.ram_history = (
    st.session_state.ram_history[-HISTORY_LIMIT:]
)

col1, col2 = st.columns(2)

with col1:

    st.subheader("🖥️ CPU Usage")

    st.line_chart(
        pd.DataFrame(
            st.session_state.cpu_history
        ).set_index("Time")
    )

with col2:

    st.subheader("🧠 RAM Usage")

    st.line_chart(
        pd.DataFrame(
            st.session_state.ram_history
        ).set_index("Time")
    )


# ---------------------------------------------------------
# Storage Information
# ---------------------------------------------------------
st.divider()

st.header("💾 Storage Information")

col1, col2, col3 = st.columns(3)

col1.metric("Total Storage", f"{total_disk:.2f} GB")
col2.metric("Used Storage", f"{used_disk:.2f} GB")
col3.metric("Free Storage", f"{free_disk:.2f} GB")

st.progress(
    max(0.0, min(disk_percent / 100.0, 1.0))
)

st.caption(
    f"Root filesystem usage: {disk_percent:.1f}%. "
    "In WSL2, this describes the Linux root filesystem "
    "and may not equal the full Windows drive."
)

with st.expander("Mounted disk partitions"):

    partitions = data.get("disk_partitions", [])

    if partitions:

        st.dataframe(
            pd.DataFrame(partitions),
            width="stretch",
            hide_index=True,
        )

    else:
        st.info(
            "No mounted partition details are available."
        )


# ---------------------------------------------------------
# CPU Information
# ---------------------------------------------------------
st.divider()

st.header("⚙️ CPU Information")

col1, col2, col3 = st.columns(3)

col1.metric(
    "Physical Cores",
    str(cpu.get("physical_cores", "Unavailable")),
)

col2.metric(
    "Logical Cores",
    str(cpu.get("logical_cores", "Unavailable")),
)

frequency = cpu.get("frequency_mhz")

col3.metric(
    "CPU Frequency",
    f"{frequency:.0f} MHz"
    if isinstance(frequency, (int, float))
    else "Unavailable",
)

st.write(
    f"**Processor:** {cpu.get('processor', 'Unavailable')}"
)


# ---------------------------------------------------------
# System Information
# ---------------------------------------------------------
st.divider()

st.header("🖥️ System Information")

col1, col2 = st.columns(2)

with col1:

    st.write(
        f"**Operating System:** {system.get('system', 'Unavailable')}"
    )

    st.write(
        f"**Kernel:** {system.get('release', 'Unavailable')}"
    )

    st.write(
        f"**Hostname:** {system.get('hostname', 'Unavailable')}"
    )

with col2:

    st.write(
        f"**Architecture:** {system.get('architecture', 'Unavailable')}"
    )

    st.write(
        f"**Uptime:** {system.get('uptime', 'Unavailable')}"
    )

    st.write(
        f"**Python:** {system.get('python_version', 'Unavailable')}"
    )


# ---------------------------------------------------------
# Network Information
# ---------------------------------------------------------
st.divider()

st.header("🌐 Network Information")

interfaces = network.get("interfaces", [])

if interfaces:

    st.dataframe(
        pd.DataFrame(interfaces),
        width="stretch",
        hide_index=True,
    )

else:

    st.info(
        "Network interface information unavailable."
    )


# ---------------------------------------------------------
# Hardware Health
# ---------------------------------------------------------
st.divider()

st.header("📋 Hardware Health Observations")

for note in health_notes:
    st.write("• " + note)

st.caption(
    "The score is a simple utilization indicator based on "
    "CPU, RAM and root-disk usage. It is not a diagnostic "
    "of physical component health."
)


# ---------------------------------------------------------
# Top Running Processes
# ---------------------------------------------------------
st.divider()

st.header("📊 Top Running Processes")

st.caption(
    "Read-only process information. "
    "No process is stopped or modified."
)

if processes:

    st.dataframe(
        pd.DataFrame(processes),
        width="stretch",
        hide_index=True,
    )

else:

    st.info(
        "Process information is unavailable."
    )


# ---------------------------------------------------------
# PDF Report
# ---------------------------------------------------------
st.divider()

st.header("📄 Download System Report")

try:

    pdf_bytes = make_pdf_report(
        data,
        health_score,
        health_label,
        health_notes,
        processes,
    )

    st.download_button(
        "⬇️ Download PDF Hardware Report",
        data=pdf_bytes,
        file_name=(
            f"linux-hardware-report-"
            f"{datetime.now():%Y%m%d-%H%M%S}.pdf"
        ),
        mime="application/pdf",
        width="stretch",
    )

except ImportError:

    st.warning(
        "PDF export needs reportlab. Install it with: "
        "python -m pip install reportlab"
    )

except Exception as error:

    st.warning(
        f"Could not create the PDF report: {error}"
    )


# ---------------------------------------------------------
# Hardware Summary
# ---------------------------------------------------------
st.divider()

st.header("📋 Hardware Summary")

if st.button("Generate Hardware Summary"):

    summary_question = (
        "Summarize my current CPU, RAM, disk, system and "
        "network readings. Give only evidence-based observations."
    )

    with st.spinner(
        "Qwen is analyzing the current hardware snapshot..."
    ):

        summary = generate_ai_response(
            summary_question,
            data,
            processes,
        )

    st.markdown(summary)


# ---------------------------------------------------------
# AI Hardware Assistant
# ---------------------------------------------------------
st.divider()

st.header("🤖 AI Hardware Assistant")

if IS_CLOUD:
    st.caption(
        "Ask questions about the cloud server's hardware. "
        "Powered by Groq Cloud AI."
    )
else:
    st.caption(
        "Ask questions about your computer. "
        "Local Qwen AI can assist with Linux hardware analysis."
    )

# Display previous chat messages
for chat_message in st.session_state.chat_history:

    with st.chat_message(chat_message["role"]):
        st.markdown(chat_message["content"])


# Chat input
question = st.chat_input(
    "Ask something about your hardware..."
)

if question:

    st.session_state.chat_history.append({
        "role": "user",
        "content": question,
    })

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):

        with st.spinner(
            "🤖 Qwen is analyzing your question..."
        ):

            answer = generate_ai_response(
                question,
                data,
                processes,
            )

        st.markdown(answer)

    st.session_state.chat_history.append({
        "role": "assistant",
        "content": answer,
    })


# ---------------------------------------------------------
# Clear Chat
# ---------------------------------------------------------
if st.button("🗑️ Clear Chat"):

    st.session_state.chat_history = []
    st.session_state.assistant_messages = new_conversation()

    st.rerun()


# ---------------------------------------------------------
# Footer
# ---------------------------------------------------------
st.divider()

if IS_CLOUD:
    st.caption(
        "Linux Hardware AI Assistant | Python · Streamlit · Groq"
    )
    st.caption("AI Backend: Groq Cloud API")
else:
    st.caption(
        "Linux Hardware AI Assistant | Python · Streamlit · Ollama"
    )
    st.caption(f"Local AI Model: {MODEL}")
    st.caption(
        "WSL2 note: Linux metrics may reflect the WSL virtual machine, "
        "not the entire Windows host."
    )