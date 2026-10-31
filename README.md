# check-local-interface

Local Linux interface monitoring for Nagios, without an SNMP agent or Python
packages. Reads sysfs counters and Linux boot identity, and stores a locked
baseline between checks. Python 3.9+.

```sh
sudo install -d -o nagios -g nagios -m 0750 /var/lib/nagios4/local-interfaces
sudo -u nagios python3 check_local_interface.py eth0 --warning 10 --critical 20
```

Replace `eth0` with the interface name. `--state-dir` overrides the state path.
The monitoring account must be able to read sysfs and write its state directory.
Root is required only for initial directory provisioning.

A down interface returns CRITICAL. Error/discard thresholds are events per
minute; inbound discards are graphed without alerting. Initial checks, reboots
and counter resets establish a new baseline without a spurious rate alert.
Perfdata contains cumulative counters with SNMP-compatible labels, allowing
RRD to derive bandwidth. State files remain outside Git.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary sysfs fixtures and a fixed boot ID. Local Nagios command definitions and deployment are intentionally outside this standalone repository.

## Local equivalent of check_snmp_int.pl

This plugin is the local Linux equivalent of `check_snmp_int.pl`, providing
interface status monitoring, traffic counters, error/discard thresholds and
Nagios performance data without requiring an SNMP agent.

While `check_snmp_int.pl` retrieves interface information remotely using SNMP,
`check_local_interface.py` reads the Linux kernel's interface statistics
directly from `/sys/class/net`.

The output format and performance-data labels are designed to be compatible
with SNMP-style interface monitoring, making it easier to reuse existing
Nagios checks and RRD graphs.

**Key differences:**

- `check_snmp_int.pl`: remote network interface monitoring via SNMP.
- `check_local_interface.py`: local Linux interface monitoring via sysfs.
- No SNMP configuration, community strings or SNMP daemon are required.
- The plugin must execute on the monitored Linux host or through a trusted
  remote execution mechanism such as NRPE.
- Traffic counters are cumulative; bandwidth rates require two samples.
- Graph compatibility depends on the existing RRD data-source configuration.

This is a functional equivalent for local monitoring, not a drop-in
replacement for the SNMP plugin's command-line interface.

## Exit codes and limitations

- OK (0): interface is up and computed monitored error rates are below thresholds.
- WARNING (1): monitored error rates reach the warning threshold.
- CRITICAL (2): interface is down or monitored error rates reach the critical threshold.
- UNKNOWN (3): invalid configuration or unavailable/inconsistent local data.

Requires Linux sysfs, Python 3.9+ and a persistent writable state directory.
Do not share a state path between unrelated hosts. The thresholds measure
errors/discards **per minute**, not a percentage of throughput.

## License

Licensed under the GNU General Public License v3.0 or later (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
