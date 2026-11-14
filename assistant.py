"""Local Ollama tool-calling orchestration with per-session context."""

from __future__ import annotations

import json
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

For questions about the user's actual computer, select and call
the relevant inspection tools.

Use tool results as the only source of machine-specific facts.
Never guess or infer unknown hardware capabilities.

For RAM usage questions:
- Call get_memory_summary.
- Report the provided GiB fields to 2 decimal places.
- Explain total, used, and available RAM separately.
- Report swap from the swap fields.
- Never say swap is unavailable when swap.total_bytes is greater than zero.

For RAM upgrade questions:
- Call get_memory_topology.
- If slot count or maximum capacity is missing,
  clearly say it cannot be determined from available system data.
- Do not estimate it from installed RAM.

For SSD/NVMe questions:
- Use get_block_devices.
- Report transport/model only when present.
- Do not assume all solid-state devices are NVMe.

For GPU questions:
- Call get_gpu_info.
- Distinguish a PCI display controller listing from detailed GPU telemetry.

For process questions:
- Use get_top_processes.
- Compare numeric ram_percent and cpu_percent.

Explain unavailable utilities and permission failures.
Never claim a tool succeeded unless ok=true.

All tools are read-only.
Do not suggest or execute arbitrary shell commands.
Keep answers concise and clear.
Swap memory must be reported accurately.
If swap total is greater than zero and used is zero,
say: "Total swap: 2 GiB, used: 0 GiB, free: 2 GiB."
Never say swap is unavailable when swap total is greater than zero.
"""


def get_tool_specs():

    descriptions = {
        "get_cpu_info":
            "Read CPU model, architecture, sockets, physical cores and logical CPUs.",

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
            "Read PCI display controllers; detailed NVIDIA metrics are not assumed.",

        "get_memory_topology":
            "Read DIMM slot count, used/free slots, installed modules, speed and maximum supported capacity when DMI permissions/data allow it.",

        "get_top_processes":
            "Read top processes sorted by RAM percentage.",

        "get_system_info":
            "Read Linux kernel/system identity."
    }

    available = discover_capabilities()

    specs = []

    for name in ALLOWED_TOOL_NAMES:

        if name == "get_gpu_info" and not (
            available.get("pci")
            or __import__("shutil").which("nvidia-smi")
        ):
            continue

        if name == "get_pci_devices" and not available.get(
            "pci", False
        ):
            continue

        if name in {
            "get_cpu_info",
            "get_memory_summary",
            "get_block_devices",
            "get_disk_usage",
            "get_network_info",
            "get_pci_devices",
            "get_system_info"
        }:

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
    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]


def _trim_history(messages):

    if len(messages) > MAX_MESSAGES:

        tail = messages[-(MAX_MESSAGES - 1):]

        while tail and tail[0].get("role") not in (
            "user",
            "assistant"
        ):
            tail = tail[1:]

        messages[:] = [messages[0]] + tail


def ask_hardware_assistant(question: str, messages=None) -> str:

    if messages is None:
        messages = new_conversation()

    if not messages or messages[0].get("role") != "system":

        messages.insert(
            0,
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        )

    messages.append({
        "role": "user",
        "content": str(question)
    })

    _trim_history(messages)

    specs = get_tool_specs()

    for _ in range(MAX_TOOL_ROUNDS):

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "tools": specs,
                "stream": False,
                "options": {
                    "temperature": 0
                }
            },
            timeout=TIMEOUT
        )

        response.raise_for_status()

        body = response.json()
        assistant = body.get("message")

        if not isinstance(assistant, dict):
            raise RuntimeError(
                "Ollama returned an invalid chat response."
            )

        messages.append(assistant)

        calls = assistant.get("tool_calls") or []

        if not calls:

            answer = (
                assistant.get("content") or ""
            ).strip()

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

            if name not in ALLOWED_TOOL_NAMES:

                result = {
                    "ok": False,
                    "error": "Rejected: tool name is not allow-listed."
                }

            else:

                result = execute_system_tool(name, args)

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

    import sys

    print(
        f"Local Linux Hardware Assistant | model={MODEL} | type exit to quit"
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