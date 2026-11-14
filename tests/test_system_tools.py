import json
import unittest
from unittest.mock import patch

import system_tools


class TestHardwareTools(unittest.TestCase):

    def test_unauthorized_tool_rejected(self):
        result = system_tools.execute_system_tool(
            "delete_files", {}
        )
        self.assertFalse(result["ok"])
        self.assertIn("Unauthorized", result["error"])

    def test_unexpected_arguments_rejected(self):
        result = system_tools.execute_system_tool(
            "get_cpu_info",
            {"command": "rm -rf /"}
        )
        self.assertFalse(result["ok"])

    def test_memory_parser(self):
        fake_output = """total used free shared buff/cache available
Mem: 8121909248 576217088 6712209408 4300800 1001418752 7545692160
Swap: 2147483648 0 2147483648
"""

        with patch.object(
            system_tools,
            "_run_fixed",
            return_value={"ok": True, "stdout": fake_output}
        ):
            result = system_tools._parse_memory()

        self.assertTrue(result["ok"])

        mem = result["data"]["mem"]
        swap = result["data"]["swap"]

        self.assertEqual(mem["total_gib"], 7.56)
        self.assertEqual(swap["total_gib"], 2.0)
        self.assertEqual(swap["used_gib"], 0.0)

    def test_cpu_parser(self):
        fake_cpu = {
            "lscpu": [
                {"field": "Model name:", "data": "Test CPU"},
                {"field": "CPU(s):", "data": "8"},
                {"field": "Core(s) per socket:", "data": "4"}
            ]
        }

        with patch.object(
            system_tools,
            "_run_fixed",
            return_value={
                "ok": True,
                "stdout": json.dumps(fake_cpu)
            }
        ):
            result = system_tools._parse_cpu()

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["model"], "Test CPU")
        self.assertEqual(result["data"]["logical_cpus"], "8")

    def test_unknown_tool_does_not_execute(self):
        with patch.object(
            system_tools,
            "_run_fixed"
        ) as mocked:
            result = system_tools.execute_system_tool(
                "unknown_tool", {}
            )

        self.assertFalse(result["ok"])
        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
