import psutil
import platform
import json


def get_cpu_info():
    return {
        "processor": platform.processor(),
        "architecture": platform.machine(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "cpu_usage": psutil.cpu_percent(interval=1)
    }


def get_memory_info():
    memory = psutil.virtual_memory()

    return {
        "total_ram_gb": round(memory.total / (1024 ** 3), 2),
        "available_ram_gb": round(memory.available / (1024 ** 3), 2),
        "used_ram_percent": memory.percent
    }


def get_disk_info():
    disk = psutil.disk_usage('/')

    return {
        "total_disk_gb": round(disk.total / (1024 ** 3), 2),
        "used_disk_gb": round(disk.used / (1024 ** 3), 2),
        "free_disk_gb": round(disk.free / (1024 ** 3), 2)
    }


def get_hardware_info():
    return {
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disk": get_disk_info()
    }


if __name__ == "__main__":
    hardware = get_hardware_info()

    print(json.dumps(hardware, indent=4))
