"""Safe, read-only Linux hardware inspection tools."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from pathlib import Path
from typing import Any


TIMEOUT_SECONDS = 8

# Fixed commands only. No user input is passed to the shell.
COMMANDS = {
    "cpu": ("lscpu", ["--json"]),
    "memory": ("free", ["--bytes"]),
    "block": (
        "lsblk",
        [
            "--json", "--bytes",
            "-o",
            "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,ROTA,TRAN,FSTYPE"
        ]
    ),
    "pci": ("lspci", ["-nn"]),
    "disk": ("df", ["-B1", "-T", "/"]),
    "network": ("ip", ["-j", "address", "show"]),
    "system": ("uname", ["-a"]),
}


def _run_fixed(key: str) -> dict[str, Any]:

    if key not in COMMANDS:
        return {
            "ok": False,
            "error": "Tool is not allow-listed."
        }

    binary, args = COMMANDS[key]

    path = shutil.which(binary)

    if not path:
        return {
            "ok": False,
            "error": f"Required utility '{binary}' is not installed."
        }

    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            shell=False
        )

        if result.returncode != 0:
            return {
                "ok": False,
                "error": result.stderr.strip()
                or f"{binary} exited with {result.returncode}."
            }

        return {
            "ok": True,
            "stdout": result.stdout.strip()
        }

    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"{binary} timed out."
        }

    except OSError as exc:
        return {
            "ok": False,
            "error": str(exc)
        }


# --------------------------------------------------
# CPU INFORMATION
# --------------------------------------------------

def _parse_cpu() -> dict:

    result = _run_fixed("cpu")

    if not result["ok"]:
        return result

    try:
        entries = json.loads(
            result["stdout"]
        ).get("lscpu", [])

        raw = {
            str(item.get("field", "")).rstrip(":"):
            item.get("data")
            for item in entries
        }

        return {
            "ok": True,
            "data": {
                "model": raw.get("Model name"),
                "architecture": raw.get("Architecture"),
                "physical_cores": raw.get("Core(s) per socket"),
                "logical_cpus": raw.get("CPU(s)"),
                "sockets": raw.get("Socket(s)"),
                "threads_per_core": raw.get("Thread(s) per core"),
                "vendor": raw.get("Vendor ID"),
                "max_mhz": raw.get("CPU max MHz"),
                "min_mhz": raw.get("CPU min MHz"),
                "virtualization": raw.get("Virtualization"),
                "raw_fields": raw
            }
        }

    except (ValueError, TypeError, AttributeError) as exc:
        return {
            "ok": False,
            "error": f"Could not parse CPU information: {exc}"
        }


# --------------------------------------------------
# RAM AND SWAP INFORMATION
# --------------------------------------------------

def _parse_memory() -> dict:

    result = _run_fixed("memory")

    if not result["ok"]:
        return result

    try:
        lines = result["stdout"].splitlines()

        memory_data = {}

        def to_gib(value):

            if value is None:
                return None

            return round(value / (1024 ** 3), 2)

        for line in lines[1:]:

            parts = line.split()

            if not parts:
                continue

            label = parts[0].lower().rstrip(":")

            if label not in ("mem", "swap"):
                continue

            values = [
                int(value)
                for value in parts[1:]
            ]

            total = values[0] if len(values) > 0 else None
            used = values[1] if len(values) > 1 else None
            free = values[2] if len(values) > 2 else None

            available = (
                values[5]
                if label == "mem" and len(values) > 5
                else None
            )

            memory_data[label] = {
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "available_bytes": available,

                "total_gib": to_gib(total),
                "used_gib": to_gib(used),
                "free_gib": to_gib(free),
                "available_gib": to_gib(available)
            }

        return {
            "ok": True,
            "data": memory_data,
            "format_note": (
                "RAM and swap values are calculated in GiB "
                "using 1024^3 bytes. "
                "Use mem.available_gib for available RAM. "
                "Use swap.total_gib, swap.used_gib and "
                "swap.free_gib for swap."
            )
        }

    except (ValueError, IndexError, TypeError) as exc:

        return {
            "ok": False,
            "error": f"Could not parse memory information: {exc}"
        }


# --------------------------------------------------
# STORAGE DEVICES
# --------------------------------------------------

def _parse_block() -> dict:

    result = _run_fixed("block")

    if not result["ok"]:
        return result

    try:
        devices = json.loads(
            result["stdout"]
        ).get("blockdevices", [])

        def normalize(items):

            output = []

            for device in items:

                name = device.get("name")
                transport = device.get("tran")

                is_nvme = (
                    str(name).startswith("nvme")
                    or str(transport).lower() == "nvme"
                )

                output.append({
                    "name": name,
                    "size_bytes": device.get("size"),
                    "type": device.get("type"),
                    "model": device.get("model"),
                    "transport": transport,
                    "is_rotational": device.get("rota"),
                    "is_nvme": is_nvme,
                    "filesystem": device.get("fstype"),
                    "mountpoint": device.get("mountpoint"),
                    "children": normalize(
                        device.get("children") or []
                    )
                })

            return output

        return {
            "ok": True,
            "data": {
                "devices": normalize(devices)
            }
        }

    except (ValueError, TypeError, AttributeError) as exc:

        return {
            "ok": False,
            "error": f"Could not parse storage information: {exc}"
        }


# --------------------------------------------------
# DISK USAGE
# --------------------------------------------------

def _parse_disk() -> dict:

    result = _run_fixed("disk")

    if not result["ok"]:
        return result

    lines = result["stdout"].splitlines()

    if len(lines) < 2:
        return {
            "ok": False,
            "error": "Unexpected disk output."
        }

    parts = lines[1].split()

    try:
        return {
            "ok": True,
            "data": {
                "filesystem": parts[0],
                "type": parts[1],
                "total_bytes": int(parts[2]),
                "used_bytes": int(parts[3]),
                "available_bytes": int(parts[4]),
                "used_percent": parts[5],
                "mountpoint": parts[6]
            }
        }

    except (ValueError, IndexError):

        return {
            "ok": True,
            "data": {
                "raw": lines[1]
            }
        }


# --------------------------------------------------
# NETWORK INFORMATION
# --------------------------------------------------

def _parse_network() -> dict:

    result = _run_fixed("network")

    if not result["ok"]:
        return result

    try:
        rows = json.loads(result["stdout"])

        interfaces = []

        for row in rows:

            interfaces.append({
                "interface": row.get("ifname"),
                "state": row.get("operstate"),

                "addresses": [
                    {
                        "family": address.get("family"),
                        "address": address.get("local"),
                        "prefixlen": address.get("prefixlen")
                    }

                    for address in row.get("addr_info", [])
                ]
            })

        return {
            "ok": True,
            "data": {
                "interfaces": interfaces
            }
        }

    except (ValueError, TypeError) as exc:

        return {
            "ok": False,
            "error": f"Could not parse network information: {exc}"
        }


# --------------------------------------------------
# GPU AND PCI INFORMATION
# --------------------------------------------------

def _parse_pci() -> dict:

    result = _run_fixed("pci")

    if not result["ok"]:
        return result

    devices = result["stdout"].splitlines()

    return {
        "ok": True,
        "data": {
            "devices": devices,

            "display_controllers": [
                item for item in devices
                if re.search(
                    r"VGA|3D controller|Display controller",
                    item,
                    re.I
                )
            ],

            "network_controllers": [
                item for item in devices
                if re.search(
                    r"Ethernet controller|Network controller",
                    item,
                    re.I
                )
            ]
        }
    }


# --------------------------------------------------
# RAM SLOT INFORMATION
# --------------------------------------------------

def _memory_topology() -> dict:

    executable = shutil.which("dmidecode")

    raw = None
    warning = None

    if executable:

        command = [
            executable,
            "--type",
            "memory"
        ]

        if os.geteuid() != 0:

            sudo = shutil.which("sudo")

            if sudo:
                command = [
                    sudo,
                    "-n",
                    executable,
                    "--type",
                    "memory"
                ]
            else:
                warning = "sudo is unavailable."

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
                shell=False
            )

            if result.returncode == 0:
                raw = result.stdout
            else:
                warning = (
                    result.stderr.strip()
                    or "DMI information unavailable."
                )

        except (OSError, subprocess.TimeoutExpired) as exc:
            warning = str(exc)

    else:
        warning = "dmidecode is not installed."

    if raw:

        sizes = re.findall(
            r"^\s*Size:\s*(.+?)\s*$",
            raw,
            re.M | re.I
        )

        installed = [
            size for size in sizes
            if not re.search(
                r"No Module Installed|Unknown|Not Specified",
                size,
                re.I
            )
        ]

        maximum = re.findall(
            r"^\s*Maximum Capacity:\s*(.+?)\s*$",
            raw,
            re.M | re.I
        )

        speeds = re.findall(
            r"^\s*Speed:\s*(.+?)\s*$",
            raw,
            re.M | re.I
        )

        return {
            "ok": True,
            "data": {
                "source": "dmidecode",
                "slot_count": len(sizes) if sizes else None,
                "used_slots": len(installed) if sizes else None,
                "free_slots": (
                    len(sizes) - len(installed)
                    if sizes else None
                ),
                "installed_module_sizes": installed,
                "maximum_capacity": (
                    maximum[0] if maximum else None
                ),
                "module_speeds": speeds,
                "maximum_capacity_verified": bool(maximum)
            },
            "warning": warning
        }

    # Safe fallback: never guess motherboard capacity or slot count.

    total = None

    try:
        for line in Path("/proc/meminfo").read_text().splitlines():

            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
                break

    except OSError:
        pass

    board = {}

    dmi_path = Path("/sys/class/dmi/id")

    for key in (
        "board_vendor",
        "board_name",
        "sys_vendor",
        "product_name",
        "bios_version"
    ):

        try:
            value = (dmi_path / key).read_text().strip()

            if value:
                board[key] = value

        except OSError:
            pass

    return {
        "ok": True,
        "data": {
            "source": "Linux fallback",
            "installed_total_bytes": total,
            "slot_count": None,
            "used_slots": None,
            "free_slots": None,
            "maximum_capacity": None,
            "maximum_capacity_verified": False,
            "board": board,
            "note": (
                "Linux does not expose reliable RAM slot count "
                "or motherboard maximum capacity in this environment."
            )
        },
        "warning": warning
    }


# --------------------------------------------------
# TOP MEMORY-USING PROCESSES
# --------------------------------------------------

def get_top_processes(limit=10) -> dict:

    try:
        import psutil

        rows = []

        for process in psutil.process_iter([
            "pid",
            "name",
            "memory_percent",
            "cpu_percent"
        ]):

            try:
                info = process.info

                rows.append({
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "ram_percent": round(
                        float(info.get("memory_percent") or 0),
                        2
                    ),
                    "cpu_percent": round(
                        float(info.get("cpu_percent") or 0),
                        1
                    )
                })

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess
            ):
                continue

        rows.sort(
            key=lambda item: item["ram_percent"],
            reverse=True
        )

        return {
            "ok": True,
            "data": rows[:max(1, min(int(limit), 20))]
        }

    except Exception as exc:

        return {
            "ok": False,
            "error": str(exc)
        }


# --------------------------------------------------
# MAIN TOOL DISPATCHER
# --------------------------------------------------

def execute_system_tool(
    tool_name: str,
    arguments: dict | None = None
) -> dict:

    """Execute only approved read-only hardware inspection tools."""

    arguments = arguments or {}

    if not isinstance(arguments, dict) or arguments:
        return {
            "ok": False,
            "error": "This inspection tool accepts no arguments."
        }

    dispatch = {
        "get_cpu_info": _parse_cpu,
        "get_memory_summary": _parse_memory,
        "get_block_devices": _parse_block,
        "get_disk_usage": _parse_disk,
        "get_network_info": _parse_network,
        "get_pci_devices": _parse_pci,
        "get_memory_topology": _memory_topology,
        "get_top_processes": get_top_processes
    }

    if tool_name == "get_system_info":

        result = _run_fixed("system")

        if not result["ok"]:
            return result

        return {
            "ok": True,
            "data": {
                "uname": result["stdout"]
            }
        }

    if tool_name == "get_gpu_info":

        result = _parse_pci()

        if not result["ok"]:
            return result

        return {
            "ok": True,
            "data": result["data"]["display_controllers"],
            "note": (
                "PCI display-controller inventory. "
                "Detailed GPU utilization and VRAM require "
                "specific vendor utilities and are not inferred."
            )
        }

    function = dispatch.get(tool_name)

    if function is None:
        return {
            "ok": False,
            "error": "Unauthorized tool name."
        }

    return function()


# --------------------------------------------------
# ALLOWED TOOL NAMES
# --------------------------------------------------

ALLOWED_TOOL_NAMES = (
    "get_cpu_info",
    "get_memory_summary",
    "get_block_devices",
    "get_disk_usage",
    "get_network_info",
    "get_pci_devices",
    "get_gpu_info",
    "get_memory_topology",
    "get_top_processes",
    "get_system_info"
)


# --------------------------------------------------
# DETECT AVAILABLE LINUX UTILITIES
# --------------------------------------------------

def discover_capabilities() -> dict:

    found = {
        name: bool(shutil.which(binary))
        for name, (binary, args) in COMMANDS.items()
    }

    found["dmidecode"] = bool(
        shutil.which("dmidecode")
    )

    found["sudo"] = bool(
        shutil.which("sudo")
    )

    return found