"""
Linux Hardware Assistant - System Tools

Features:
- CPU information
- RAM and swap information
- Storage devices
- Disk usage
- Network interfaces
- GPU detection
- RAM slot information (when available)
- Top running processes
- Linux system information

Security:
- Uses fixed, read-only commands.
- Does not use shell=True.
- Does not execute arbitrary user commands.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


TIMEOUT_SECONDS = 8


# --------------------------------------------------
# 1. FIXED COMMAND ALLOW-LIST
# --------------------------------------------------

COMMANDS = {
    "cpu": ("lscpu", ["--json"]),

    "memory": ("free", ["--bytes"]),

    "block": (
        "lsblk",
        [
            "--json",
            "--bytes",
            "-o",
            "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,ROTA,TRAN,FSTYPE"
        ]
    ),

    "pci": ("lspci", ["-nn"]),

    "disk": ("df", ["-B1", "-T", "/"]),

    "network": ("ip", ["-j", "address", "show"]),

    "system": ("uname", ["-a"])
}


# --------------------------------------------------
# 2. SAFE COMMAND EXECUTION
# --------------------------------------------------

def run_fixed_command(command_name):

    if command_name not in COMMANDS:
        return {
            "ok": False,
            "error": "Command is not allow-listed."
        }

    binary, arguments = COMMANDS[command_name]

    executable = shutil.which(binary)

    if not executable:
        return {
            "ok": False,
            "error": f"{binary} is not installed."
        }

    try:

        result = subprocess.run(
            [executable] + arguments,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            shell=False
        )

        if result.returncode != 0:

            return {
                "ok": False,
                "error": (
                    result.stderr.strip()
                    or f"{binary} returned error code {result.returncode}"
                )
            }

        return {
            "ok": True,
            "stdout": result.stdout.strip()
        }

    except subprocess.TimeoutExpired:

        return {
            "ok": False,
            "error": f"{binary} command timed out."
        }

    except OSError as error:

        return {
            "ok": False,
            "error": str(error)
        }


# --------------------------------------------------
# 3. CPU INFORMATION
# --------------------------------------------------

def get_cpu_info():

    result = run_fixed_command("cpu")

    if not result["ok"]:
        return result

    try:

        output = json.loads(result["stdout"])

        entries = output.get("lscpu", [])

        cpu_data = {}

        for item in entries:

            field = str(item.get("field", "")).rstrip(":")

            cpu_data[field] = item.get("data")

        return {
            "ok": True,

            "data": {
                "model": cpu_data.get("Model name"),

                "architecture": cpu_data.get("Architecture"),

                "vendor": cpu_data.get("Vendor ID"),

                "sockets": cpu_data.get("Socket(s)"),

                "physical_cores_per_socket":
                    cpu_data.get("Core(s) per socket"),

                "threads_per_core":
                    cpu_data.get("Thread(s) per core"),

                "logical_cpus":
                    cpu_data.get("CPU(s)"),

                "maximum_frequency":
                    cpu_data.get("CPU max MHz"),

                "minimum_frequency":
                    cpu_data.get("CPU min MHz"),

                "virtualization":
                    cpu_data.get("Virtualization")
            }
        }

    except Exception as error:

        return {
            "ok": False,
            "error": f"CPU parsing failed: {error}"
        }


# --------------------------------------------------
# 4. RAM AND SWAP INFORMATION
# --------------------------------------------------

def get_memory_summary():

    result = run_fixed_command("memory")

    if not result["ok"]:
        return result

    try:

        lines = result["stdout"].splitlines()

        memory_data = {}

        def convert_to_gib(value):

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
                if value.isdigit()
            ]

            if len(values) < 3:
                continue

            row = {
                "total_bytes": values[0],
                "used_bytes": values[1],
                "free_bytes": values[2]
            }

            row["total_gib"] = convert_to_gib(values[0])

            row["used_gib"] = convert_to_gib(values[1])

            row["free_gib"] = convert_to_gib(values[2])

            if label == "mem" and len(values) >= 6:

                row["available_bytes"] = values[5]

                row["available_gib"] = convert_to_gib(
                    values[5]
                )

            memory_data[label] = row

        return {
            "ok": True,
            "data": memory_data,
            "note": (
                "Memory values are provided in bytes and GiB. "
                "Available RAM is different from free RAM."
            )
        }

    except Exception as error:

        return {
            "ok": False,
            "error": f"Memory parsing failed: {error}"
        }


# --------------------------------------------------
# 5. STORAGE DEVICE INFORMATION
# --------------------------------------------------

def get_block_devices():

    result = run_fixed_command("block")

    if not result["ok"]:
        return result

    try:

        output = json.loads(result["stdout"])

        devices = output.get("blockdevices", [])

        def parse_devices(device_list):

            parsed = []

            for device in device_list:

                name = device.get("name")

                transport = device.get("tran")

                is_nvme = (
                    str(name).startswith("nvme")
                    or str(transport).lower() == "nvme"
                )

                parsed.append({

                    "name": name,

                    "model": device.get("model"),

                    "size_bytes": device.get("size"),

                    "type": device.get("type"),

                    "transport": transport,

                    "is_rotational": device.get("rota"),

                    "is_nvme": is_nvme,

                    "filesystem": device.get("fstype"),

                    "mountpoint": device.get("mountpoint"),

                    "children": parse_devices(
                        device.get("children") or []
                    )

                })

            return parsed

        return {
            "ok": True,
            "data": {
                "devices": parse_devices(devices)
            }
        }

    except Exception as error:

        return {
            "ok": False,
            "error": f"Storage parsing failed: {error}"
        }


# --------------------------------------------------
# 6. DISK USAGE
# --------------------------------------------------

def get_disk_usage():

    result = run_fixed_command("disk")

    if not result["ok"]:
        return result

    try:

        lines = result["stdout"].splitlines()

        if len(lines) < 2:

            return {
                "ok": False,
                "error": "Unexpected disk usage output."
            }

        values = lines[1].split()

        return {
            "ok": True,

            "data": {

                "filesystem": values[0],

                "filesystem_type": values[1],

                "total_bytes": int(values[2]),

                "used_bytes": int(values[3]),

                "available_bytes": int(values[4]),

                "used_percentage": values[5],

                "mountpoint": values[6]

            }
        }

    except Exception as error:

        return {
            "ok": False,
            "error": f"Disk parsing failed: {error}"
        }


# --------------------------------------------------
# 7. NETWORK INFORMATION
# --------------------------------------------------

def get_network_info():

    result = run_fixed_command("network")

    if not result["ok"]:
        return result

    try:

        interfaces = json.loads(result["stdout"])

        parsed = []

        for interface in interfaces:

            addresses = []

            for address in interface.get("addr_info", []):

                addresses.append({

                    "family": address.get("family"),

                    "address": address.get("local"),

                    "prefix_length": address.get("prefixlen")

                })

            parsed.append({

                "interface": interface.get("ifname"),

                "state": interface.get("operstate"),

                "addresses": addresses

            })

        return {
            "ok": True,
            "data": {
                "interfaces": parsed
            }
        }

    except Exception as error:

        return {
            "ok": False,
            "error": f"Network parsing failed: {error}"
        }


# --------------------------------------------------
# 8. PCI DEVICES
# --------------------------------------------------

def get_pci_devices():

    result = run_fixed_command("pci")

    if not result["ok"]:
        return result

    devices = result["stdout"].splitlines()

    return {

        "ok": True,

        "data": {

            "devices": devices,

            "display_controllers": [
                device
                for device in devices
                if re.search(
                    r"VGA|3D controller|Display controller",
                    device,
                    re.IGNORECASE
                )
            ],

            "network_controllers": [
                device
                for device in devices
                if re.search(
                    r"Ethernet controller|Network controller",
                    device,
                    re.IGNORECASE
                )
            ]

        }
    }


# --------------------------------------------------
# 9. GPU INFORMATION
# --------------------------------------------------

def get_gpu_info():

    result = get_pci_devices()

    if not result["ok"]:
        return result

    return {

        "ok": True,

        "data": result["data"]["display_controllers"],

        "note": (
            "These are PCI display-controller devices. "
            "Detailed GPU utilization and VRAM information "
            "may require vendor-specific utilities."
        )
    }


# --------------------------------------------------
# 10. RAM SLOT AND MEMORY TOPOLOGY
# --------------------------------------------------

def get_memory_topology():

    executable = shutil.which("dmidecode")

    warning = None

    if not executable:

        warning = "dmidecode is not installed."

    else:

        command = [executable, "--type", "memory"]

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

                sizes = re.findall(
                    r"^\s*Size:\s*(.+?)\s*$",
                    raw,
                    re.MULTILINE | re.IGNORECASE
                )

                installed = [
                    size
                    for size in sizes
                    if not re.search(
                        r"No Module Installed|Unknown|Not Specified",
                        size,
                        re.IGNORECASE
                    )
                ]

                capacities = re.findall(
                    r"^\s*Maximum Capacity:\s*(.+?)\s*$",
                    raw,
                    re.MULTILINE | re.IGNORECASE
                )

                speeds = re.findall(
                    r"^\s*Speed:\s*(.+?)\s*$",
                    raw,
                    re.MULTILINE | re.IGNORECASE
                )

                types = re.findall(
                    r"^\s*Type:\s*(.+?)\s*$",
                    raw,
                    re.MULTILINE | re.IGNORECASE
                )

                return {

                    "ok": True,

                    "data": {

                        "source": "dmidecode",

                        "slot_count": (
                            len(sizes) if sizes else None
                        ),

                        "used_slots": (
                            len(installed) if sizes else None
                        ),

                        "free_slots": (
                            len(sizes) - len(installed)
                            if sizes else None
                        ),

                        "installed_modules": installed,

                        "maximum_capacity": (
                            capacities[0]
                            if capacities else None
                        ),

                        "module_speeds": speeds,

                        "module_types": types,

                        "maximum_capacity_verified": bool(
                            capacities
                        )

                    },

                    "warning": warning

                }

            warning = (
                result.stderr.strip()
                or "dmidecode failed or permission was denied."
            )

        except Exception as error:

            warning = str(error)

    # Fallback when DMI data is unavailable.

    total_memory = None

    try:

        for line in Path("/proc/meminfo").read_text().splitlines():

            if line.startswith("MemTotal:"):

                total_memory = int(line.split()[1]) * 1024

                break

    except OSError:
        pass

    board_information = {}

    dmi_path = Path("/sys/class/dmi/id")

    for field in (
        "board_vendor",
        "board_name",
        "sys_vendor",
        "product_name",
        "bios_version"
    ):

        try:

            value = (dmi_path / field).read_text().strip()

            if value:

                board_information[field] = value

        except OSError:
            pass

    return {

        "ok": True,

        "data": {

            "source": "Linux fallback",

            "installed_total_bytes": total_memory,

            "slot_count": None,

            "used_slots": None,

            "free_slots": None,

            "maximum_capacity": None,

            "maximum_capacity_verified": False,

            "board_information": board_information,

            "note": (
                "RAM slot count and maximum motherboard "
                "capacity are unavailable from the current "
                "Linux environment."
            )

        },

        "warning": warning

    }


# --------------------------------------------------
# 11. TOP PROCESSES
# --------------------------------------------------

def get_top_processes(limit=10):

    try:

        import psutil

        processes = []

        for process in psutil.process_iter(
            [
                "pid",
                "name",
                "memory_percent",
                "cpu_percent"
            ]
        ):

            try:

                info = process.info

                processes.append({

                    "pid": info.get("pid"),

                    "name": info.get("name"),

                    "ram_percent": round(
                        float(info.get("memory_percent") or 0),
                        2
                    ),

                    "cpu_percent": round(
                        float(info.get("cpu_percent") or 0),
                        2
                    )

                })

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess
            ):

                continue

        processes.sort(
            key=lambda item: item["ram_percent"],
            reverse=True
        )

        return {

            "ok": True,

            "data": processes[:max(1, min(int(limit), 20))]

        }

    except Exception as error:

        return {
            "ok": False,
            "error": str(error)
        }


# --------------------------------------------------
# 12. SYSTEM INFORMATION
# --------------------------------------------------

def get_system_info():

    result = run_fixed_command("system")

    if not result["ok"]:
        return result

    return {

        "ok": True,

        "data": {
            "uname": result["stdout"]
        }

    }


# --------------------------------------------------
# 13. TOOL DISPATCHER
# --------------------------------------------------

ALLOWED_TOOL_NAMES = [

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

]


def execute_system_tool(tool_name, arguments=None):

    """
    Executes only approved inspection functions.

    Model-generated arguments are not used to construct
    shell commands. Each tool uses fixed command parameters.
    """

    dispatch = {

        "get_cpu_info": get_cpu_info,

        "get_memory_summary": get_memory_summary,

        "get_block_devices": get_block_devices,

        "get_disk_usage": get_disk_usage,

        "get_network_info": get_network_info,

        "get_pci_devices": get_pci_devices,

        "get_gpu_info": get_gpu_info,

        "get_memory_topology": get_memory_topology,

        "get_top_processes": get_top_processes,

        "get_system_info": get_system_info

    }

    function = dispatch.get(tool_name)

    if function is None:

        return {

            "ok": False,

            "error": "Unauthorized tool name."

        }

    # Tool calls do not accept arbitrary command arguments.
    # The optional arguments parameter is intentionally ignored.

    if tool_name == "get_top_processes":

        return function()

    return function()


# --------------------------------------------------
# 14. AVAILABLE SYSTEM CAPABILITIES
# --------------------------------------------------

def discover_capabilities():

    capabilities = {

        "cpu": bool(shutil.which("lscpu")),

        "memory": bool(shutil.which("free")),

        "block": bool(shutil.which("lsblk")),

        "pci": bool(shutil.which("lspci")),

        "disk": bool(shutil.which("df")),

        "network": bool(shutil.which("ip")),

        "system": bool(shutil.which("uname")),

        "dmidecode": bool(shutil.which("dmidecode")),

        "sudo": bool(shutil.which("sudo")),

        "psutil": False

    }

    try:

        import psutil

        capabilities["psutil"] = True

    except ImportError:

        pass

    return capabilities


# --------------------------------------------------
# 15. DIRECT TEST
# --------------------------------------------------

if __name__ == "__main__":

    print("\nLINUX HARDWARE ASSISTANT - SYSTEM TEST")

    print("\nAvailable capabilities:")

    print(
        json.dumps(
            discover_capabilities(),
            indent=4
        )
    )

    print("\nCPU information:")

    print(
        json.dumps(
            get_cpu_info(),
            indent=4
        )
    )

    print("\nMemory information:")

    print(
        json.dumps(
            get_memory_summary(),
            indent=4
        )
    )

    print("\nStorage information:")

    print(
        json.dumps(
            get_block_devices(),
            indent=4
        )
    )

    print("\nGPU information:")

    print(
        json.dumps(
            get_gpu_info(),
            indent=4
        )
    )

    print("\nMemory topology:")

    print(
        json.dumps(
            get_memory_topology(),
            indent=4
        )
    )