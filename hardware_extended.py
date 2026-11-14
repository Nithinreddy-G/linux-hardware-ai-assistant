"""Extended, read-only Linux hardware information helpers."""
import json
import platform
import socket
import time

import psutil


def _gb(value):
    return round(value / (1024 ** 3), 2)


def get_system_info():
    try:
        uptime_seconds = int(time.time() - psutil.boot_time())
    except Exception:
        uptime_seconds = None

    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "uptime_seconds": uptime_seconds,
        "uptime": (
            f"{uptime_seconds // 86400} days, "
            f"{(uptime_seconds % 86400) // 3600} hours"
            if uptime_seconds is not None else "Unavailable"
        ),
    }


def get_cpu_info():
    frequency = psutil.cpu_freq()
    processor = platform.processor() or "Unavailable"
    # Linux often exposes a more useful processor model in /proc/cpuinfo.
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    processor = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass

    return {
        "processor": processor,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        # psutil returns a percentage, e.g. 0.5 means 0.5%, not 50%.
        "cpu_usage": psutil.cpu_percent(interval=0.2),
        "frequency_mhz": round(frequency.current, 2) if frequency else None,
    }


def get_memory_info():
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total_gb": _gb(memory.total),
        "used_gb": _gb(memory.used),
        "available_gb": _gb(memory.available),
        "used_percent": round(memory.percent, 1),
        "swap_total_gb": _gb(swap.total),
        "swap_used_gb": _gb(swap.used),
        "swap_percent": round(swap.percent, 1),
    }


def get_disk_info():
    disk = psutil.disk_usage("/")
    return {
        "mountpoint": "/",
        "total_gb": _gb(disk.total),
        "used_gb": _gb(disk.used),
        "free_gb": _gb(disk.free),
        "used_percent": round(disk.percent, 1),
    }


def get_disk_partitions():
    partitions = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "filesystem": part.fstype or "Unknown",
                "total_gb": _gb(usage.total),
                "used_gb": _gb(usage.used),
                "free_gb": _gb(usage.free),
                "used_percent": round(usage.percent, 1),
            })
        except (PermissionError, OSError):
            continue
    return partitions


def get_network_info():
    interfaces = []
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    for name, entries in addresses.items():
        ipv4 = next((entry.address for entry in entries if entry.family == socket.AF_INET), None)
        interfaces.append({
            "name": name,
            "ipv4": ipv4 or "Unavailable",
            "is_up": bool(stats[name].isup) if name in stats else None,
        })
    return {"hostname": socket.gethostname(), "interfaces": interfaces}


def get_top_processes(limit=10):
    rows = []
    for proc in psutil.process_iter(["pid", "name", "username", "memory_percent", "cpu_percent"]):
        try:
            info = proc.info
            rows.append({
                "PID": info.get("pid"),
                "Process": info.get("name") or "Unknown",
                "User": info.get("username") or "Unavailable",
                "CPU (%)": round(float(info.get("cpu_percent") or 0), 1),
                "RAM (%)": round(float(info.get("memory_percent") or 0), 2),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    rows.sort(key=lambda item: (item["RAM (%)"], item["CPU (%)"]), reverse=True)
    return rows[:max(1, min(int(limit), 50))]


def get_hardware_info():
    """Return one consistent snapshot using the existing dashboard data keys."""
    return {
        "system": get_system_info(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disk": get_disk_info(),
        "disk_partitions": get_disk_partitions(),
        "network": get_network_info(),
    }


if __name__ == "__main__":
    print(json.dumps(get_hardware_info(), indent=4))
