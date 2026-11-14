"""Local Ollama tool-calling orchestration with per-session context."""

from __future__ import annotations

import json
import re
import shutil
import requests

from system_tools import (
    execute_system_tool,
    ALLOWED_TOOL_NAMES,
    discover_capabilities
)


MODEL = "qwen2.5:1.5b"
OLLAMA_URL = "http://localhost:11434/api/chat"

TIMEOUT = 90
MAX_TOOL_ROUNDS = 5
MAX_MESSAGES = 24


SYSTEM_PROMPT = """
You are a precise local Linux hardware assistant.

Use inspection tools as the only source of machine-specific facts.
Never guess or infer unknown hardware capabilities.

CPU:
- sockets is the number of physical CPU sockets.
- physical_cores_per_socket is the physical core count in each socket.
- logical_cpus is the total number of logical processors (hardware threads).
- Total physical cores = sockets * physical_cores_per_socket when both exist.
- Never confuse physical cores with logical CPUs.

RAM:
- Report total, used, free, and available RAM as separate values.
- Free RAM is currently unused memory.
- Available RAM is an estimate of memory available to applications,
  including reclaimable cache. It is not the same as free RAM.
- Report swap from the swap fields.
- Never confuse RAM used with RAM total.

RAM upgrades:
- Call get_memory_topology.
- If slot count or maximum capacity is missing, say it cannot be determined.
- Do not estimate it from installed RAM.

Storage:
- Call get_block_devices.
- Report device/model/capacity/filesystem/mount/transport only when supplied.
- A "Virtual Disk" is a virtual device, not proof of a physical laptop drive.
- Do not infer physical HDD/SSD type from a virtual device's rotational flag.
- Do not claim NVMe unless explicitly identified.
- If physical drive type cannot be established, say so.

GPU:
- Call get_gpu_info.
- PCI address (for example fe14:00:00.0), device class (for example [0302]),
  and vendor/device ID (for example [1414:008e]) are different fields.
- Never call the PCI address the vendor/device ID.
- Report vendor and device name as returned by the tool.
- A PCI display/3D-controller listing does not necessarily identify
  the physical GPU installed in the laptop.
- Do not invent VRAM, utilization, temperature, or clock information.

Processes:
- Use get_top_processes and compare numeric ram_percent and cpu_percent.

General:
- Explain unavailable utilities and permission failures.
- Never claim a tool succeeded unless ok=true.
- All tools are read-only. Do not execute arbitrary shell commands.
- Keep answers concise and accurate.
"""


def get_tool_specs():

    descriptions = {
        "get_cpu_info":
            "Read CPU model, architecture, sockets, physical cores per socket and total logical CPUs.",
        "get_memory_summary":
            "Read physical RAM and swap totals, used, free and available bytes.",
        "get_block_devices":
            "Read storage device model, capacity, transport, rotational flag, filesystem and mount points.",
        "get_disk_usage":
            "Read root filesystem total, used and available bytes.",
        "get_network_info":
            "Read network interface names, state and IP addresses.",
        "get_pci_devices":
            "Read PCI hardware inventory including controllers.",
        "get_gpu_info":
            "Read PCI display/3D controllers; detailed GPU metrics are not assumed.",
        "get_memory_topology":
            "Read DIMM slot count, used/free slots, installed modules, speed and maximum supported capacity when DMI permissions/data allow it.",
        "get_top_processes":
            "Read top processes sorted by RAM percentage.",
        "get_system_info":
            "Read Linux kernel/system identity."
    }

    available = discover_capabilities()
    specs = []

    binary_map = {
        "get_cpu_info": "lscpu",
        "get_memory_summary": "free",
        "get_block_devices": "lsblk",
        "get_disk_usage": "df",
        "get_network_info": "ip",
        "get_pci_devices": "lspci",
        "get_system_info": "uname"
    }

    capability_map = {
        "lscpu": "cpu",
        "free": "memory",
        "lsblk": "block",
        "df": "disk",
        "ip": "network",
        "lspci": "pci",
        "uname": "system"
    }

    for name in ALLOWED_TOOL_NAMES:

        if name not in descriptions:
            continue

        if name == "get_gpu_info":
            if not (
                available.get("pci", False)
                or shutil.which("nvidia-smi")
            ):
                continue

        if name == "get_pci_devices" and not available.get("pci", False):
            continue

        if name in binary_map:
            binary = binary_map[name]
            capability = capability_map[binary]
            if not available.get(capability, False):
                continue

        specs.append({
            "type": "function",
            "function": {
                "name": name,
                "description": descriptions[name],
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        })

    return specs


def new_conversation():
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _trim_history(messages):

    if len(messages) > MAX_MESSAGES:
        tail = messages[-(MAX_MESSAGES - 1):]

        while tail and tail[0].get("role") not in ("user", "assistant"):
            tail = tail[1:]

        messages[:] = [messages[0]] + tail


def _add_cpu_summary(result):

    def process(item):
        if isinstance(item, dict):
            sockets = item.get("sockets")
            cores_per_socket = item.get("physical_cores_per_socket")
            logical_cpus = item.get("logical_cpus")

            if (
                isinstance(sockets, int)
                and isinstance(cores_per_socket, int)
                and sockets >= 0
                and cores_per_socket >= 0
            ):
                item["total_physical_cores"] = sockets * cores_per_socket

            if isinstance(logical_cpus, int):
                item["logical_cpu_count"] = logical_cpus

            for value in item.values():
                process(value)

        elif isinstance(item, list):
            for value in item:
                process(value)

    if isinstance(result, (dict, list)):
        process(result)

    return result


def _is_success(result):
    return isinstance(result, dict) and result.get("ok") is True


def _format_memory_answer(result):
    if not _is_success(result):
        return None

    data = result.get("data") or {}
    mem = data.get("mem") or {}
    swap = data.get("swap") or {}

    required = ("total_gib", "used_gib", "free_gib", "available_gib")
    if not all(key in mem for key in required):
        return None

    lines = [
        "Here is your system's memory information:",
        f"- Total RAM: {mem['total_gib']:.2f} GiB",
        f"- Used RAM: {mem['used_gib']:.2f} GiB",
        f"- Free RAM: {mem['free_gib']:.2f} GiB",
        f"- Available RAM: {mem['available_gib']:.2f} GiB"
    ]

    if all(key in swap for key in ("total_gib", "used_gib", "free_gib")):
        lines.extend([
            f"- Total swap: {swap['total_gib']:.2f} GiB",
            f"- Used swap: {swap['used_gib']:.2f} GiB",
            f"- Free swap: {swap['free_gib']:.2f} GiB"
        ])

    lines.append(
        "Free RAM is currently unused memory. Available RAM is an estimate "
        "of memory that applications can use, including reclaimable cache."
    )
    return "\n".join(lines)


def _format_gpu_answer(result):
    if not _is_success(result):
        return None

    data = result.get("data") or []
    entries = data if isinstance(data, list) else [data]
    if not entries:
        return "The GPU inspection tool did not report any PCI display or 3D controller."

    descriptions = []
    for entry in entries:
        if not isinstance(entry, str):
            continue

        # Typical lspci format:
        # address class: vendor device name [vendor_id:device_id]
        match = re.match(
            r"^\s*(\S+)\s+(.+?)\s+\[([0-9a-fA-F]{4})\]:\s*(.+?)\s+\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]\s*$",
            entry
        )

        if match:
            address, device_class, class_code, device_name, vendor_device_id = match.groups()
            descriptions.append(
                f"- Reported device: {device_name}\n"
                f"- PCI address: {address}\n"
                f"- Device class: {device_class} [{class_code}]\n"
                f"- PCI vendor/device ID: {vendor_device_id}"
            )
        else:
            descriptions.append(f"- PCI entry: {entry}")

    if not descriptions:
        return "The GPU tool returned data, but its PCI entry could not be parsed safely."

    return (
        "The system reports the following PCI display/3D-controller information:\n"
        + "\n".join(descriptions)
        + "\n\nBecause this system is running under WSL2, this PCI entry does not "
          "by itself identify the physical GPU installed in the Windows laptop. "
          "Detailed GPU utilization and VRAM metrics were not provided by this tool."
    )


def _deterministic_answer(question):
    """
    Use exact tool values for RAM and GPU questions instead of asking
    the small language model to paraphrase or reinterpret numeric data.
    Returns None when the question is outside these two categories.
    """

    q = question.lower()

    memory_terms = ("ram", "memory", "swap")
    gpu_terms = ("gpu", "graphics card", "graphics processor", "video card")

    if any(term in q for term in memory_terms):
        result = execute_system_tool("get_memory_summary", {})
        answer = _format_memory_answer(result)
        if answer:
            return answer

    if any(term in q for term in gpu_terms):
        result = execute_system_tool("get_gpu_info", {})
        answer = _format_gpu_answer(result)
        if answer:
            return answer

    return None


def ask_hardware_assistant(question: str, messages=None) -> str:

    if messages is None:
        messages = new_conversation()

    if not messages or messages[0].get("role") != "system":
        messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    question = str(question)
    messages.append({"role": "user", "content": question})
    _trim_history(messages)

    # For RAM and GPU questions, present exact inspected values directly.
    direct_answer = _deterministic_answer(question)
    if direct_answer is not None:
        messages.append({"role": "assistant", "content": direct_answer})
        _trim_history(messages)
        return direct_answer

    specs = get_tool_specs()

    for _ in range(MAX_TOOL_ROUNDS):

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "tools": specs,
                "stream": False,
                "options": {"temperature": 0}
            },
            timeout=TIMEOUT
        )

        response.raise_for_status()
        body = response.json()
        assistant = body.get("message")

        if not isinstance(assistant, dict):
            raise RuntimeError("Ollama returned an invalid chat response.")

        messages.append(assistant)
        calls = assistant.get("tool_calls") or []

        if not calls:
            answer = (assistant.get("content") or "").strip()
            return answer or (
                "The local model returned an empty answer. "
                "Please rephrase the question."
            )

        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name")
            args = fn.get("arguments") or {}

            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_invalid": args}

            if not isinstance(args, dict):
                args = {"_invalid": args}

            if name not in ALLOWED_TOOL_NAMES:
                result = {
                    "ok": False,
                    "error": "Rejected: tool name is not allow-listed."
                }
            else:
                try:
                    result = execute_system_tool(name, args)
                    if name == "get_cpu_info":
                        result = _add_cpu_summary(result)
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}

            messages.append({
                "role": "tool",
                "tool_name": name or "unknown",
                "content": json.dumps(
                    result,
                    ensure_ascii=False,
                    default=str
                )
            })

    return (
        "I reached the maximum number of inspection steps. "
        "Please ask a more specific question."
    )


if __name__ == "__main__":

    print(
        f"Local Linux Hardware Assistant | "
        f"model={MODEL} | type exit to quit"
    )

    history = new_conversation()

    while True:
        q = input("\nYou: ").strip()

        if q.lower() in {"exit", "quit"}:
            break

        try:
            answer = ask_hardware_assistant(q, history)
            print("\nAssistant:", answer)

        except requests.RequestException as exc:
            print("\nOllama request failed:", exc)

        except Exception as exc:
            print("\nAssistant error:", exc)
