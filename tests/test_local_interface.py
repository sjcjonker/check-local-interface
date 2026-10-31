"""Unit tests for local Linux interface checks without SNMP or privileges."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "check_local_interface.py"
spec = importlib.util.spec_from_file_location("check_local_interface", PLUGIN)
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class LocalInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.device = self.root / "sys" / "ens3"
        (self.device / "statistics").mkdir(parents=True)
        (self.device / "operstate").write_text("up\n")
        (self.device / "speed").write_text("1000\n")
        self.values = {"rx_bytes": 1000000, "tx_bytes": 2000000,
                       "rx_errors": 0, "tx_errors": 0,
                       "rx_dropped": 0, "tx_dropped": 1}
        self.save()
        original_read = Path.read_text
        def read_fixture(path, *args, **kwargs):
            if str(path) == '/proc/sys/kernel/random/boot_id':
                return 'fixture-boot-id\n'
            return original_read(path, *args, **kwargs)
        boot_patch = patch.object(Path, 'read_text', read_fixture)
        boot_patch.start()
        self.addCleanup(boot_patch.stop)

    def save(self):
        for name, count in self.values.items():
            (self.device / "statistics" / name).write_text(str(count))

    def check(self, at):
        argv = ["plugin", "ens3", "--sysfs", str(self.root / "sys"),
                "--state-dir", str(self.root / "state")]
        stdout = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(plugin.time, "monotonic", return_value=at), contextlib.redirect_stdout(stdout):
            rc = plugin.run()
        return rc, stdout.getvalue().strip()

    def test_baseline_rates_and_counter_perfdata(self):
        first_rc, first = self.check(100)
        self.assertEqual(first_rc, 0)
        self.assertIn("baseline initialized", first)
        self.values["rx_bytes"] += 60000
        self.values["tx_bytes"] += 120000
        self.values["tx_dropped"] += 1
        self.save()
        rc, line = self.check(160)
        self.assertEqual(rc, 0)
        self.assertIn("ens3:UP (in=1.0KBps/out=2.0KBps/", line)
        self.assertIn("discard-out=1.0", line)
        self.assertIn("'ens3_in_octet'=1060000c", line)
        self.assertIn("'ens3_out_discard'=2c", line)
        self.assertIn("'ens3_speed_bps'=1000000000", line)

    def test_counter_reset_is_not_spurious(self):
        self.check(100)
        self.values["rx_bytes"] = 1
        self.save()
        rc, line = self.check(160)
        self.assertEqual(rc, 0)
        self.assertIn("baseline initialized", line)

    def test_down_interface_is_critical(self):
        (self.device / "operstate").write_text("down\n")
        rc, line = self.check(100)
        self.assertEqual(rc, 2)
        self.assertIn("ens3:DOWN", line)

    def test_rejects_nonfinite_thresholds(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                argv = ["plugin", "ens3", "--sysfs", str(self.root / "sys"),
                        "--state-dir", str(self.root / "state"),
                        f"--warning={value}"]
                with patch.object(sys, "argv", argv):
                    with self.assertRaisesRegex(ValueError, "invalid thresholds"):
                        plugin.run()
        for value in ("nan", "inf", "-inf"):
            with self.subTest(critical=value):
                argv = ["plugin", "ens3", "--sysfs", str(self.root / "sys"),
                        "--state-dir", str(self.root / "state"),
                        f"--critical={value}"]
                with patch.object(sys, "argv", argv):
                    with self.assertRaisesRegex(ValueError, "invalid thresholds"):
                        plugin.run()


if __name__ == "__main__":
    unittest.main()
