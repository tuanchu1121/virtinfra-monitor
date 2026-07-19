#!/usr/bin/env python3
"""
VirtInfra Agent v15 daemon (per-disk storage I/O + monitor-synchronized abuse)

Collects:
  1) VM/tap network traffic from libvirt domiflist + /sys/class/net/<tap>/statistics
  2) VM CPU/RAM/Disk from virsh domstats
  3) Host CPU/RAM/Disk/filesystem from /proc, /sys, df
  4) Physical/uplink NIC counters for br0/br1 bridge members
  5) IPv4 addresses assigned directly to br0/br1
  6) Agent self-health timings
  7) Local 15-second VM network peak sampling with directional sustained PPS timers and one 5-minute HTTP push
  8) Physical and VM deltas used by server-side Consumption rollups

Important CPU behavior:
  - cpu_percent is now CORE-based:
      100% = 1 full CPU core
      400% = 4 full CPU cores
  - cpu_normalized_percent is also sent:
      100% = all assigned vCPU fully used
"""

import os
import json
import gzip
import time
import subprocess
import urllib.request
import urllib.error
import ipaddress
import copy
import signal
import threading
import stat
from pathlib import Path

API = os.environ.get("VIRTINFRA_AGENT_API") or os.environ.get("BW_AGENT_API", "http://103.199.19.207:8080/push")
TOKEN = os.environ.get("VIRTINFRA_AGENT_TOKEN") or os.environ.get("BW_AGENT_TOKEN", "123456")
STATE = os.environ.get("VIRTINFRA_AGENT_STATE") or os.environ.get("BW_AGENT_STATE", "/var/lib/virtinfra-agent/state.json")
NODE_NAME = (os.environ.get("VIRTINFRA_AGENT_NODE") or os.environ.get("BW_AGENT_NODE") or os.uname().nodename).strip()

COLLECT_VM_NET = os.environ.get("BW_AGENT_COLLECT_VM_NET", "1") == "1"
COLLECT_VM_PERF = os.environ.get("BW_AGENT_COLLECT_VM_PERF", "1") == "1"
COLLECT_NODE_HOST = os.environ.get("BW_AGENT_COLLECT_NODE_HOST", "1") == "1"
COLLECT_PHYSICAL_NET = os.environ.get("BW_AGENT_COLLECT_PHYSICAL_NET", "1") == "1"

# Default mapping:
#   public  -> physical/uplink member of br0
#   private -> physical/uplink member of br1
#
# Override examples:
#   BW_AGENT_BRIDGE_ROLES="public:br0,private:br1"
#   BW_AGENT_BRIDGE_ROLES="public:br-public,private:br-private"
BRIDGE_ROLES = os.environ.get("BW_AGENT_BRIDGE_ROLES", "public:br0,private:br1")
# Bridge collection is optional by default because valid nodes may expose only
# one bridge or use a different topology. Operators can explicitly require roles
# with BW_AGENT_REQUIRED_BRIDGE_ROLES="public,private".
REQUIRED_BRIDGE_ROLES = os.environ.get("BW_AGENT_REQUIRED_BRIDGE_ROLES", "")

API_TIMEOUT = int(os.environ.get("BW_AGENT_API_TIMEOUT", "15"))
DOMSTATS_TIMEOUT = int(os.environ.get("BW_AGENT_DOMSTATS_TIMEOUT", "60"))
VIRSH_LIST_TIMEOUT = int(os.environ.get("BW_AGENT_VIRSH_LIST_TIMEOUT", "30"))
DOMIFLIST_TIMEOUT = int(os.environ.get("BW_AGENT_DOMIFLIST_TIMEOUT", "30"))

DRY_RUN = os.environ.get("BW_AGENT_DRY_RUN", "0") == "1"

# Daemon scheduling. Sampling is local only; HTTP push remains every 5 minutes.
SAMPLE_SECONDS = max(5, int(os.environ.get("VIRTINFRA_AGENT_SAMPLE_SECONDS") or os.environ.get("BW_AGENT_SAMPLE_SECONDS", "15")))
PUSH_SECONDS = max(60, int(os.environ.get("VIRTINFRA_AGENT_PUSH_SECONDS") or os.environ.get("BW_AGENT_PUSH_SECONDS", "300")))
MAX_LOAD = float(os.environ.get("BW_AGENT_MAX_LOAD", "160"))
# Preserve the old agent behavior by default: high load is reported, but CPU/RAM/disk
# collection is NOT silently removed. Set this to 1 only if you explicitly accept
# network-only payloads while the node is overloaded.
SKIP_HEAVY_ON_OVERLOAD = os.environ.get("BW_AGENT_SKIP_HEAVY_ON_OVERLOAD", "0") == "1"
PPS_WARN = max(0.0, float(os.environ.get("BW_AGENT_PPS_WARN", "200000")))
MBPS_WARN = max(0.0, float(os.environ.get("BW_AGENT_MBPS_WARN", "800")))
STALE_IFACE_SECONDS = max(120, int(os.environ.get("BW_AGENT_STALE_IFACE_SECONDS", "600")))
RUNTIME = os.environ.get("VIRTINFRA_AGENT_RUNTIME") or os.environ.get("BW_AGENT_RUNTIME", "/var/lib/virtinfra-agent/runtime.json")
QUIET = os.environ.get("BW_AGENT_QUIET", "0") == "1"
HTTP_GZIP = os.environ.get("BW_AGENT_HTTP_GZIP", "1") == "1"
HTTP_GZIP_MIN_BYTES = max(0, int(os.environ.get("BW_AGENT_HTTP_GZIP_MIN_BYTES", "1024")))

AGENT_VERSION = 15
STOP_EVENT = threading.Event()


def ms_since(start):
    return int((time.monotonic() - start) * 1000)


def _append_health_item(health, field, message):
    try:
        items = health.setdefault(field, [])
        message = str(message)[:300]
        if message not in items and len(items) < 50:
            items.append(message)
    except Exception:
        pass


def add_error(health, message):
    _append_health_item(health, "errors", message)


def add_note(health, message):
    _append_health_item(health, "notes", message)


def run(cmd, timeout=30):
    return subprocess.check_output(
        cmd,
        universal_newlines=True,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    ).strip()


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def load_state():
    try:
        with open(STATE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, separators=(",", ":"))
    os.replace(tmp, STATE)


def read_text(path, default=""):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return default


def read_counter(path):
    try:
        return int(Path(path).read_text().strip())
    except Exception:
        return 0


def delta_counter(new, old):
    new = safe_int(new, 0)
    old = safe_int(old, new)
    if new < old:
        return 0
    return new - old


def parse_bridge_roles(value):
    roles = []
    for item in (value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            role, bridge = item.split(":", 1)
        elif "=" in item:
            role, bridge = item.split("=", 1)
        else:
            continue
        role = role.strip().lower()
        bridge = bridge.strip()
        if role and bridge:
            roles.append((role, bridge))
    if not roles:
        roles = [("public", "br0"), ("private", "br1")]
    return roles


def parse_required_bridge_roles(value):
    return {
        item.strip().lower()
        for item in (value or "").replace(";", ",").split(",")
        if item.strip()
    }


def bridge_role_is_required(role):
    return str(role or "").strip().lower() in parse_required_bridge_roles(
        REQUIRED_BRIDGE_ROLES
    )


def record_bridge_unavailable(health, role, bridge, status):
    role = str(role or "").strip().lower()
    bridge = str(bridge or "").strip()
    status = str(status or "not_configured").strip().lower()
    if bridge_role_is_required(role):
        add_error(
            health,
            "required bridge unavailable role=%s bridge=%s status=%s"
            % (role, bridge, status),
        )
    else:
        add_note(
            health,
            "optional bridge omitted role=%s bridge=%s status=%s"
            % (role, bridge, status),
        )


def parse_ip_addr_json(text):
    """Parse `ip -j address show` output into a stable IPv4 CIDR list."""
    try:
        payload = json.loads(text or "[]")
    except Exception:
        return {"ipv4": [], "primary_ipv4": ""}

    if isinstance(payload, dict):
        payload = [payload]

    found = []
    seen = set()

    for link in payload if isinstance(payload, list) else []:
        if not isinstance(link, dict):
            continue
        for item in link.get("addr_info") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("family") or "").lower() != "inet":
                continue

            local = str(item.get("local") or "").strip()
            if not local:
                continue

            try:
                ip_obj = ipaddress.ip_address(local)
            except ValueError:
                continue

            flags = {str(flag).lower() for flag in (item.get("flags") or [])}
            if "tentative" in flags or "dadfailed" in flags:
                continue
            if ip_obj.is_loopback or ip_obj.is_unspecified or ip_obj.is_multicast:
                continue

            prefixlen = safe_int(item.get("prefixlen"), 32)
            cidr = "%s/%s" % (local, prefixlen)
            if cidr in seen:
                continue
            seen.add(cidr)
            found.append({
                "cidr": cidr,
                "scope": str(item.get("scope") or ""),
                "dynamic": "dynamic" in flags,
                "secondary": "secondary" in flags,
            })

    scope_rank = {"global": 0, "site": 1, "link": 2, "host": 3}
    found.sort(key=lambda item: (
        scope_rank.get(item.get("scope") or "", 9),
        1 if item.get("secondary") else 0,
        1 if item.get("dynamic") else 0,
        item.get("cidr") or "",
    ))

    ipv4 = [item["cidr"] for item in found]
    return {
        "ipv4": ipv4,
        "primary_ipv4": ipv4[0] if ipv4 else "",
    }


def collect_bridge_addresses(health=None):
    """Collect IPv4 addresses assigned directly to br0/br1 bridge devices."""
    rows = []
    for role, bridge in parse_bridge_roles(BRIDGE_ROLES):
        base = Path("/sys/class/net") / bridge
        if not base.exists():
            record_bridge_unavailable(health, role, bridge, "not_configured")
            continue

        try:
            raw = run(["ip", "-j", "-4", "address", "show", "dev", bridge], timeout=10)
            addresses = parse_ip_addr_json(raw)
        except Exception as exc:
            add_error(health, "cannot read bridge IPv4 for %s:%s: %s" % (role, bridge, exc))
            addresses = {"ipv4": [], "primary_ipv4": ""}

        meta = iface_metadata(bridge)
        rows.append({
            "role": role,
            "bridge": bridge,
            "ipv4": addresses["ipv4"],
            "primary_ipv4": addresses["primary_ipv4"],
            "operstate": meta["operstate"],
            "carrier": meta["carrier"],
            "mtu": meta["mtu"],
            "mac": meta["address"],
        })
    return rows

def get_vm_names(health=None):
    """Return (active_domain_names, inventory_complete).

    A successful empty list is complete. A virsh failure is incomplete so the
    monitor does not mark every previously known VM as missing.
    """
    try:
        out = run(["virsh", "list", "--name"], timeout=VIRSH_LIST_TIMEOUT)
        return [x.strip() for x in out.splitlines() if x.strip()], True
    except Exception as e:
        add_error(health, "virsh list failed: %s" % e)
        return [], False


def parse_domiflist(vm, health=None):
    rows = []
    try:
        out = run(["virsh", "domiflist", vm], timeout=DOMIFLIST_TIMEOUT)
    except Exception as e:
        add_error(health, "domiflist failed for %s: %s" % (vm, e))
        return rows

    for line in out.splitlines():
        p = line.split()
        if len(p) < 5:
            continue
        if p[0] == "Interface" or p[0].startswith("-"):
            continue
        rows.append({"iface": p[0], "bridge": p[2], "mac": p[4]})
    return rows


def collect_interface_counters(iface):
    base = Path("/sys/class/net") / iface / "statistics"
    if not base.exists():
        return None
    return {
        "rx": read_counter(base / "rx_bytes"),
        "tx": read_counter(base / "tx_bytes"),
        "rx_packets": read_counter(base / "rx_packets"),
        "tx_packets": read_counter(base / "tx_packets"),
        "rx_drop": read_counter(base / "rx_dropped"),
        "tx_drop": read_counter(base / "tx_dropped"),
        "rx_error": read_counter(base / "rx_errors"),
        "tx_error": read_counter(base / "tx_errors"),
    }


def collect_network(vm_names, state, health=None):
    rows = []
    for vm in vm_names:
        for nic in parse_domiflist(vm, health=health):
            iface = nic["iface"]
            bridge = nic["bridge"]
            mac = nic["mac"]

            counters = collect_interface_counters(iface)
            if not counters:
                continue

            key = "net:%s:%s" % (vm, iface)
            old_key = "%s:%s" % (vm, iface)  # old agent state key
            old = state.get(key)
            if old is None:
                old = state.get(old_key, {})

            row = {
                "vm_uuid": vm,
                "iface": iface,
                "bridge": bridge,
                "mac": mac,
                "rx_delta": delta_counter(counters["rx"], old.get("rx", counters["rx"])),
                "tx_delta": delta_counter(counters["tx"], old.get("tx", counters["tx"])),
                "rx_packets_delta": delta_counter(counters["rx_packets"], old.get("rx_packets", counters["rx_packets"])),
                "tx_packets_delta": delta_counter(counters["tx_packets"], old.get("tx_packets", counters["tx_packets"])),
                "rx_drop_delta": delta_counter(counters["rx_drop"], old.get("rx_drop", counters["rx_drop"])),
                "tx_drop_delta": delta_counter(counters["tx_drop"], old.get("tx_drop", counters["tx_drop"])),
                "rx_error_delta": delta_counter(counters["rx_error"], old.get("rx_error", counters["rx_error"])),
                "tx_error_delta": delta_counter(counters["tx_error"], old.get("tx_error", counters["tx_error"])),
            }
            state[key] = counters
            rows.append(row)
    return rows


def split_domstats_blocks(text):
    blocks = []
    current_domain = None
    current_stats = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Domain:"):
            if current_domain is not None:
                blocks.append((current_domain, current_stats))
            parts = line.split("'", 2)
            current_domain = parts[1] if len(parts) >= 2 else line.replace("Domain:", "").strip()
            current_stats = {}
            continue
        if current_domain is None:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            current_stats[k.strip()] = v.strip()
    if current_domain is not None:
        blocks.append((current_domain, current_stats))
    return blocks


def classify_vm_disk(vm_uuid, target, source):
    """Classify libvirt blocks without assuming vda/vdb roles."""
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source:
        return "auxiliary"
    filename = os.path.basename(source).lower()
    if filename in {"cloud-drive.img", "config-drive.img", "cloudinit.img", "seed.img", "cidata.img"}:
        return "auxiliary"
    if "/vf-data/server/" in source and filename.endswith(".img"):
        return "auxiliary"
    if filename.endswith(".iso") or target.startswith(("sd", "hd")) and "cloud-drive" in filename:
        return "auxiliary"
    return "customer"


def parse_mount_inventory(filesystems):
    """Build a longest-prefix mount map for VM image paths.

    Do not require SOURCE to start with /dev/.  Some production storage stacks
    expose LVM, device-mapper, multipath, ZFS, bind or controller-specific
    source names.  The mountpoint is still authoritative for mapping a VM image
    path, while block-device metadata is best-effort.
    """
    mounts = []
    for fs in filesystems or []:
        if not isinstance(fs, dict):
            continue
        mount = str(fs.get("mount") or "").rstrip("/") or "/"
        device = str(fs.get("device") or "")
        if not mount:
            continue
        mounts.append({
            "mount": mount,
            "device": device,
            "block": device_to_block_name(device, fs.get("maj_min")) or "",
            "fstype": str(fs.get("fstype") or ""),
            "size": safe_int(fs.get("size"), 0),
            "used": safe_int(fs.get("used"), 0),
            "avail": safe_int(fs.get("avail"), 0),
            "use_percent": safe_float(fs.get("use_percent"), 0.0),
        })
    mounts.sort(key=lambda x: len(x["mount"]), reverse=True)
    return mounts


def map_source_to_mount(source, mounts):
    source = os.path.realpath(str(source or "")) if source else ""
    if not source:
        return {}
    for item in mounts or []:
        mount = item.get("mount") or "/"
        if mount == "/":
            matched = source.startswith("/")
        else:
            matched = source == mount or source.startswith(mount + "/")
        if matched:
            return dict(item)
    return {}


def read_block_stats(block_name):
    """Return Linux block counters using the stable fields from /sys/class/block/*/stat."""
    try:
        parts = (Path("/sys/class/block") / block_name / "stat").read_text().split()
        return {
            "read_ios": safe_int(parts[0], 0),
            "read_bytes": safe_int(parts[2], 0) * 512,
            "read_ms": safe_int(parts[3], 0),
            "write_ios": safe_int(parts[4], 0),
            "write_bytes": safe_int(parts[6], 0) * 512,
            "write_ms": safe_int(parts[7], 0),
            "io_in_progress": safe_int(parts[8], 0),
            "io_ms": safe_int(parts[9], 0),
            "weighted_io_ms": safe_int(parts[10], 0),
        }
    except Exception:
        return {}


def md_raid_level(block_name):
    try:
        return read_text("/sys/class/block/%s/md/level" % block_name, "")
    except Exception:
        return ""


def collect_vm_perf(state, now_ts, health=None):
    vms = []
    try:
        out = run(["virsh", "domstats", "--list-active", "--vcpu", "--balloon", "--block"], timeout=DOMSTATS_TIMEOUT)
    except Exception as e:
        add_error(health, "virsh domstats failed: %s" % e)
        return vms

    # One filesystem scan for the whole node. Mapping is done in memory.
    filesystems = collect_filesystems()
    mount_inventory = parse_mount_inventory(filesystems)

    for vm_uuid, stats in split_domstats_blocks(out):
        vcpu_current = safe_int(stats.get("vcpu.current"), 0)
        vcpu_time_ns = 0
        detected_vcpus = 0
        for k, v in stats.items():
            if k.startswith("vcpu.") and k.endswith(".time"):
                vcpu_time_ns += safe_int(v, 0)
                detected_vcpus += 1
        if vcpu_current <= 0:
            vcpu_current = detected_vcpus

        key = "perf:%s" % vm_uuid
        old = state.get(key, {})
        old_time = safe_int(old.get("time"), now_ts)
        interval = max(1, now_ts - old_time)
        cpu_time_delta_ns = delta_counter(vcpu_time_ns, old.get("vcpu_time_ns", vcpu_time_ns))
        cpu_core_percent = max(0.0, (cpu_time_delta_ns / float(interval) / 1000000000.0) * 100.0)
        cpu_normalized_percent = max(0.0, min(100.0, cpu_core_percent / float(vcpu_current))) if vcpu_current > 0 else 0.0

        block_indexes = sorted({k.split(".")[1] for k in stats if k.startswith("block.") and len(k.split(".")) >= 3 and k.split(".")[1].isdigit()}, key=int)
        disks = []
        current_disk_state = {}
        total_read_delta = total_write_delta = 0
        total_read_reqs_delta = total_write_reqs_delta = 0

        for idx in block_indexes:
            prefix = "block.%s" % idx
            target = str(stats.get(prefix + ".name") or "").strip()
            source = str(stats.get(prefix + ".path") or "").strip()
            role = classify_vm_disk(vm_uuid, target, source)
            counters = {
                "read_bytes": safe_int(stats.get(prefix + ".rd.bytes"), 0),
                "write_bytes": safe_int(stats.get(prefix + ".wr.bytes"), 0),
                "read_reqs": safe_int(stats.get(prefix + ".rd.reqs"), 0),
                "write_reqs": safe_int(stats.get(prefix + ".wr.reqs"), 0),
            }
            identity = "%s|%s" % (target, source)
            old_disk = (old.get("disks") or {}).get(identity, {})
            rd = delta_counter(counters["read_bytes"], old_disk.get("read_bytes", counters["read_bytes"]))
            wd = delta_counter(counters["write_bytes"], old_disk.get("write_bytes", counters["write_bytes"]))
            rr = delta_counter(counters["read_reqs"], old_disk.get("read_reqs", counters["read_reqs"]))
            wr = delta_counter(counters["write_reqs"], old_disk.get("write_reqs", counters["write_reqs"]))
            current_disk_state[identity] = counters
            mount = map_source_to_mount(source, mount_inventory)
            item = {
                "index": safe_int(idx, 0), "target": target, "source": source, "role": role,
                "mount": mount.get("mount", ""), "storage_device": mount.get("device", ""),
                "storage_block": mount.get("block", ""), "storage_fstype": mount.get("fstype", ""),
                "capacity_bytes": safe_int(stats.get(prefix + ".capacity"), 0),
                "allocation_bytes": safe_int(stats.get(prefix + ".allocation"), 0),
                "physical_bytes": safe_int(stats.get(prefix + ".physical"), 0),
                "read_delta": rd, "write_delta": wd,
                "read_reqs_delta": rr, "write_reqs_delta": wr,
                "interval_seconds": interval,
            }
            disks.append(item)
            if role == "customer":
                total_read_delta += rd; total_write_delta += wd
                total_read_reqs_delta += rr; total_write_reqs_delta += wr

        state[key] = {"time": now_ts, "vcpu_time_ns": vcpu_time_ns, "disks": current_disk_state}
        vms.append({
            "vm_uuid": vm_uuid, "vcpu_current": vcpu_current,
            "cpu_percent": round(cpu_core_percent, 2),
            "cpu_core_percent": round(cpu_core_percent, 2),
            "cpu_normalized_percent": round(cpu_normalized_percent, 2),
            "ram_current_kib": safe_int(stats.get("balloon.current"), 0),
            "ram_maximum_kib": safe_int(stats.get("balloon.maximum"), 0),
            "ram_rss_kib": safe_int(stats.get("balloon.rss"), 0),
            "ram_available_kib": safe_int(stats.get("balloon.available"), 0),
            "ram_unused_kib": safe_int(stats.get("balloon.unused"), 0),
            "ram_usable_kib": safe_int(stats.get("balloon.usable"), 0),
            "disk_read_delta": total_read_delta,
            "disk_write_delta": total_write_delta,
            "disk_read_reqs_delta": total_read_reqs_delta,
            "disk_write_reqs_delta": total_write_reqs_delta,
            "disk_count": sum(1 for d in disks if d.get("role") == "customer"),
            "disks": disks,
        })
    return vms


def parse_loadavg():
    try:
        p = Path("/proc/loadavg").read_text().split()
        return safe_float(p[0]), safe_float(p[1]), safe_float(p[2])
    except Exception:
        return 0.0, 0.0, 0.0


def parse_meminfo():
    vals = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            k, rest = line.split(":", 1)
            vals[k] = safe_int(rest.strip().split()[0], 0) * 1024
    except Exception:
        pass
    mem_total = vals.get("MemTotal", 0)
    mem_available = vals.get("MemAvailable", 0)
    mem_used = max(0, mem_total - mem_available) if mem_total else 0
    swap_total = vals.get("SwapTotal", 0)
    swap_free = vals.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free) if swap_total else 0
    return mem_total, mem_available, mem_used, swap_total, swap_used


def _device_maj_min(device):
    """Return kernel MAJ:MIN for a block device path."""
    try:
        st = os.stat(str(device or ""))
        devno = st.st_rdev if stat.S_ISBLK(st.st_mode) else 0
        if devno:
            return f"{os.major(devno)}:{os.minor(devno)}"
    except Exception:
        pass
    return ""


def collect_swap_filesystems():
    """Expose active swap devices as real node-storage rows.

    Swap is not mounted, so neither df nor findmnt reports it as a filesystem.
    /proc/swaps is the authoritative inventory.  Capacity values are converted
    from KiB to bytes and block-backed swap keeps MAJ:MIN so sysfs I/O can be
    sampled exactly like a mounted filesystem.
    """
    rows = []
    try:
        lines = Path("/proc/swaps").read_text(encoding="utf-8", errors="replace").splitlines()[1:]
    except Exception:
        lines = []
    for index, raw in enumerate(lines, 1):
        parts = raw.split()
        if len(parts) < 4:
            continue
        source, swap_type, size_kib, used_kib = parts[:4]
        size = max(0, safe_int(size_kib, 0)) * 1024
        used = max(0, safe_int(used_kib, 0)) * 1024
        avail = max(0, size - used)
        mount = "SWAP" if index == 1 else f"SWAP {index}"
        rows.append({
            "device": source,
            "maj_min": _device_maj_min(source) if swap_type == "partition" else "",
            "fstype": "swap",
            "mount": mount,
            "size": size,
            "used": used,
            "avail": avail,
            "use_percent": (used * 100.0 / size) if size > 0 else 0.0,
            "fsroot": "/",
            "submount": False,
        })
    return rows


def parse_proc_stat_cpu():
    try:
        parts = Path("/proc/stat").read_text().splitlines()[0].split()
        nums = [safe_int(x, 0) for x in parts[1:]]
        total = sum(nums)
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        return total, idle
    except Exception:
        return 0, 0


def parse_uptime_seconds():
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except Exception:
        return 0


def _walk_findmnt_rows(items):
    """Yield every findmnt JSON item, including nested child mounts.

    Some util-linux versions return a tree even when JSON is requested.  A
    shallow loop sees only `/` and silently loses a separate `/home` mount.
    """
    for item in items or []:
        if not isinstance(item, dict):
            continue
        yield item
        yield from _walk_findmnt_rows(item.get("children") or [])


def _filesystem_mount_allowed(mount):
    mount = str(mount or "").strip()
    if not mount or mount == "-":
        return False
    if mount.startswith(("/run", "/sys", "/proc", "/dev")):
        return False
    return True


def _statvfs_capacity(mount):
    try:
        st = os.statvfs(mount)
        unit = safe_int(getattr(st, "f_frsize", 0), 0) or safe_int(getattr(st, "f_bsize", 0), 0)
        size = max(0, unit * safe_int(st.f_blocks, 0))
        avail = max(0, unit * safe_int(st.f_bavail, 0))
        free = max(0, unit * safe_int(st.f_bfree, 0))
        used = max(0, size - free)
        pct = (used * 100.0 / size) if size > 0 else 0.0
        return size, used, avail, pct
    except Exception:
        return 0, 0, 0, 0.0


def _mount_maj_min(mount):
    try:
        st = os.stat(mount)
        return "%s:%s" % (os.major(st.st_dev), os.minor(st.st_dev))
    except Exception:
        return ""


def _collect_df_filesystems():
    """Capacity source of truth.

    `df -P` is intentionally collected even when findmnt works.  This avoids a
    util-linux compatibility trap where an older findmnt rejects SIZE/USED
    columns and a separate LVM `/home` silently disappears from the payload.
    """
    try:
        out = run([
            "df", "-P", "-T", "-B1",
            "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay",
        ], timeout=20)
    except Exception:
        return {}

    result = {}
    for raw in out.splitlines()[1:]:
        parts = raw.split(None, 6)
        if len(parts) < 7:
            continue
        device, fstype, size_s, used_s, avail_s, pct_s, mount = parts
        mount = str(mount or "").strip()
        if not _filesystem_mount_allowed(mount):
            continue
        result[mount] = {
            "device": str(device or "").strip(),
            "maj_min": _mount_maj_min(mount),
            "fstype": str(fstype or "").strip(),
            "mount": mount,
            "size": max(0, safe_int(size_s, 0)),
            "used": max(0, safe_int(used_s, 0)),
            "avail": max(0, safe_int(avail_s, 0)),
            "use_percent": max(0.0, safe_float(str(pct_s).rstrip("%"), 0.0)),
            "fsroot": "/",
            "submount": False,
        }
    return result


def _collect_findmnt_metadata():
    """Return mount metadata without depending on optional capacity columns."""
    ignored_fs = {
        "tmpfs", "devtmpfs", "squashfs", "overlay", "tracefs", "debugfs",
        "securityfs", "pstore", "efivarfs", "cgroup", "cgroup2", "proc", "sysfs",
    }
    commands = (
        ["findmnt", "--list", "--json", "--real", "--output", "SOURCE,FSTYPE,TARGET,MAJ:MIN,FSROOT"],
        ["findmnt", "--json", "--real", "--output", "SOURCE,FSTYPE,TARGET,MAJ:MIN,FSROOT"],
        ["findmnt", "--list", "--json", "--real", "--output", "SOURCE,FSTYPE,TARGET,MAJ:MIN"],
        ["findmnt", "--json", "--real", "--output", "SOURCE,FSTYPE,TARGET,MAJ:MIN"],
    )
    for args in commands:
        try:
            payload = json.loads(run(args, timeout=20) or "{}")
        except Exception:
            continue
        result = {}
        for item in _walk_findmnt_rows(payload.get("filesystems") or []):
            mount = str(item.get("target") or "").strip()
            if not _filesystem_mount_allowed(mount):
                continue
            source = str(item.get("source") or "").strip()
            fstype = str(item.get("fstype") or "").strip()
            if fstype in ignored_fs:
                continue
            fsroot = str(item.get("fsroot") or "/").strip() or "/"
            # systemd service sandboxes expose bind aliases such as
            # /dev/md126[/etc] -> /etc.  They are not independent filesystems
            # and must not appear as separate node storage rows.
            submount = fsroot != "/" or ("[" in source and source.endswith("]"))
            base_source = source.split("[", 1)[0] if "[" in source else source
            result[mount] = {
                "device": base_source,
                "maj_min": str(item.get("maj:min") or item.get("maj_min") or "").strip(),
                "fstype": fstype,
                "mount": mount,
                "fsroot": fsroot,
                "submount": bool(submount),
            }
        if result:
            return result
    return {}


def _filesystem_identity(row):
    maj_min = str(row.get("maj_min") or "").strip()
    if maj_min:
        return "maj:" + maj_min
    device = str(row.get("device") or "").strip()
    if "[" in device:
        device = device.split("[", 1)[0]
    if device.startswith("/dev/"):
        try:
            device = os.path.realpath(device)
        except Exception:
            pass
    return "dev:" + device if device else "mount:" + str(row.get("mount") or "")


def _dedupe_filesystem_roots(rows):
    """Keep one real mount root per underlying filesystem.

    The agent runs inside a hardened systemd namespace.  `/etc`, `/usr`,
    `/tmp`, `/var/lib/virtinfra-agent`, and similar paths may therefore appear as bind
    aliases of `/`.  They share the same MAJ:MIN and are deliberately collapsed
    to the shortest real mount, while a separate LVM `/home` remains because it
    has its own MAJ:MIN.
    """
    chosen = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        mount = str(row.get("mount") or "").rstrip("/") or "/"
        row["mount"] = mount
        if not _filesystem_mount_allowed(mount):
            continue
        if row.get("submount"):
            continue
        key = _filesystem_identity(row)
        old = chosen.get(key)
        rank = (0 if mount == "/" else 1, mount.count("/"), len(mount), mount)
        if old is None:
            chosen[key] = (rank, row)
            continue
        if rank < old[0]:
            chosen[key] = (rank, row)
    result = [item[1] for item in chosen.values()]
    result.sort(key=lambda x: (0 if x.get("mount") == "/" else 1, len(str(x.get("mount") or "")), str(x.get("mount") or "")))
    for row in result:
        row.pop("fsroot", None)
        row.pop("submount", None)
    return result


def collect_filesystems():
    """Collect only real filesystem roots and never lose a separate `/home`.

    Capacity comes from `df -P`; findmnt enriches SOURCE/FSTYPE/MAJ:MIN.  Both
    sources are merged instead of treating either one as an all-or-nothing
    result.  This works on older AlmaLinux util-linux builds, LVM/device-mapper,
    mdraid, and long mapper names.
    """
    df_rows = _collect_df_filesystems()
    findmnt_rows = _collect_findmnt_metadata()
    mounts = set(df_rows) | set(findmnt_rows)
    merged = []
    for mount in mounts:
        base = dict(df_rows.get(mount) or {})
        meta = dict(findmnt_rows.get(mount) or {})
        if not base:
            size, used, avail, pct = _statvfs_capacity(mount)
            base = {
                "mount": mount, "size": size, "used": used,
                "avail": avail, "use_percent": pct,
            }
        # Prefer findmnt's canonical block source and MAJ:MIN, but never blank
        # a working df value when an older findmnt omits a field.
        for key in ("device", "maj_min", "fstype", "fsroot", "submount"):
            value = meta.get(key)
            if value not in (None, ""):
                base[key] = value
        base.setdefault("device", "")
        base.setdefault("maj_min", _mount_maj_min(mount))
        base.setdefault("fstype", "")
        base.setdefault("fsroot", "/")
        base.setdefault("submount", False)
        base["mount"] = mount
        merged.append(base)
    return _dedupe_filesystem_roots(merged)

def device_to_block_name(device, maj_min=""):
    """Resolve a mounted source to the kernel block name used by sysfs.

    MAJ:MIN is authoritative for LVM/device-mapper and avoids relying on a
    possibly long, aliased or bracket-suffixed source string.
    """
    maj_min = str(maj_min or "").strip()
    if maj_min:
        try:
            link = Path("/sys/dev/block") / maj_min
            if link.exists():
                name = os.path.basename(os.path.realpath(str(link)))
                if (Path("/sys/class/block") / name / "stat").exists():
                    return name
        except Exception:
            pass

    device = str(device or "").strip()
    if not device:
        return None
    # findmnt may render subvolume/root suffixes as /dev/mapper/vg-lv[/path].
    if "[" in device and device.endswith("]"):
        device = device.split("[", 1)[0]
    if not device.startswith("/dev/"):
        return None
    for candidate in (os.path.realpath(device), device):
        try:
            name = os.path.basename(candidate)
            if (Path("/sys/class/block") / name / "stat").exists():
                return name
        except Exception:
            pass
    return None


def read_block_bytes(block_name):
    try:
        parts = (Path("/sys/class/block") / block_name / "stat").read_text().split()
        # /sys/block stat: read sectors field 3, write sectors field 7, sector = 512 bytes.
        read_sectors = safe_int(parts[2], 0)
        write_sectors = safe_int(parts[6], 0)
        return read_sectors * 512, write_sectors * 512
    except Exception:
        return 0, 0


def collect_node_host(state, now_ts, interval):
    load1, load5, load15 = parse_loadavg()
    mem_total, mem_available, mem_used, swap_total, swap_used = parse_meminfo()
    uptime_seconds = parse_uptime_seconds()
    cpu_total, cpu_idle = parse_proc_stat_cpu()
    old_cpu = state.get("host:cpu", {})
    delta_total = delta_counter(cpu_total, safe_int(old_cpu.get("total"), cpu_total))
    delta_idle = delta_counter(cpu_idle, safe_int(old_cpu.get("idle"), cpu_idle))
    cpu_percent = max(0.0, min(100.0, ((delta_total - delta_idle) / float(delta_total)) * 100.0)) if delta_total > 0 else 0.0
    state["host:cpu"] = {"total": cpu_total, "idle": cpu_idle, "time": now_ts}

    filesystems = collect_filesystems()
    # Swap is a real block-backed storage consumer but has no mountpoint, so
    # add it explicitly after filesystem discovery.
    filesystems.extend(collect_swap_filesystems())
    storage_devices = []
    total_read_delta = total_write_delta = 0
    total_read_ios_delta = total_write_ios_delta = 0

    # Read each kernel block counter once, but keep every mount in the payload.
    # This preserves a separate /home even when a long device-mapper name or a
    # bind/multipath source would previously be skipped.  Node totals count each
    # underlying block only once to avoid double-counting aliases.
    block_samples = {}
    counted_blocks = set()
    for fs in filesystems:
        block = device_to_block_name(fs.get("device"), fs.get("maj_min")) or ""
        rd = wd = rr = wr = io_ms = weighted_ms = 0
        if block:
            if block not in block_samples:
                current = read_block_stats(block)
                if current:
                    old = state.get("host:block:%s" % block, {})
                    rd = delta_counter(current.get("read_bytes"), old.get("read_bytes", current.get("read_bytes")))
                    wd = delta_counter(current.get("write_bytes"), old.get("write_bytes", current.get("write_bytes")))
                    rr = delta_counter(current.get("read_ios"), old.get("read_ios", current.get("read_ios")))
                    wr = delta_counter(current.get("write_ios"), old.get("write_ios", current.get("write_ios")))
                    io_ms = delta_counter(current.get("io_ms"), old.get("io_ms", current.get("io_ms")))
                    weighted_ms = delta_counter(current.get("weighted_io_ms"), old.get("weighted_io_ms", current.get("weighted_io_ms")))
                    state["host:block:%s" % block] = dict(current, time=now_ts)
                block_samples[block] = (rd, wd, rr, wr, io_ms, weighted_ms)
            else:
                rd, wd, rr, wr, io_ms, weighted_ms = block_samples[block]

            if block not in counted_blocks:
                counted_blocks.add(block)
                total_read_delta += rd
                total_write_delta += wd
                total_read_ios_delta += rr
                total_write_ios_delta += wr

        storage_devices.append({
            "mount": fs.get("mount", ""),
            "device": fs.get("device", ""),
            "block": block,
            "raid_level": md_raid_level(block) if block else "",
            "fstype": fs.get("fstype", ""),
            "size": safe_int(fs.get("size"), 0),
            "used": safe_int(fs.get("used"), 0),
            "avail": safe_int(fs.get("avail"), 0),
            "use_percent": safe_float(fs.get("use_percent"), 0.0),
            "read_delta": rd,
            "write_delta": wd,
            "read_ios_delta": rr,
            "write_ios_delta": wr,
            "read_bps": rd / float(interval) if interval > 0 else 0.0,
            "write_bps": wd / float(interval) if interval > 0 else 0.0,
            "read_iops": rr / float(interval) if interval > 0 else 0.0,
            "write_iops": wr / float(interval) if interval > 0 else 0.0,
            "util_percent": min(100.0, io_ms / float(interval * 10)) if interval > 0 else 0.0,
            "weighted_io_ms_delta": weighted_ms,
        })

    return {
        "load1": round(load1, 2), "load5": round(load5, 2), "load15": round(load15, 2),
        "cpu_count": os.cpu_count() or 0, "cpu_percent": round(cpu_percent, 2),
        "mem_total": mem_total, "mem_available": mem_available, "mem_used": mem_used,
        "swap_total": swap_total, "swap_used": swap_used,
        "disk_read_delta": total_read_delta, "disk_write_delta": total_write_delta,
        "disk_read_reqs_delta": total_read_ios_delta, "disk_write_reqs_delta": total_write_ios_delta,
        "disk_read_bps": round(total_read_delta / float(interval), 2) if interval > 0 else 0.0,
        "disk_write_bps": round(total_write_delta / float(interval), 2) if interval > 0 else 0.0,
        "uptime_seconds": uptime_seconds, "filesystems": filesystems, "storage_devices": storage_devices,
    }


def is_bridge_member_candidate_uplink(iface):
    """Return True for physical/uplink-like bridge members.

    We intentionally exclude VM tap/vnet interfaces because VM traffic is already
    collected separately by collect_network().
    """
    if not iface:
        return False

    # Very common VM/tap names in libvirt/VirtFusion/KVM environments.
    if iface.isdigit():
        return False
    lowered = iface.lower()
    if lowered.startswith(("vnet", "tap", "tun", "veth", "virbr", "fwbr", "fwpr", "fwln", "qvb", "qvo", "qbr")):
        return False

    base = Path("/sys/class/net") / iface
    if not base.exists():
        return False

    # PCI/USB physical NIC normally has /device.
    if (base / "device").exists():
        return True

    # Bond/team/VLAN can be the real bridge uplink even without /device.
    if Path("/proc/net/bonding").joinpath(iface).exists():
        return True
    if (base / "bonding").exists():
        return True
    if Path("/proc/net/vlan").joinpath(iface).exists():
        return True

    # VLAN/macvlan/other stacked uplinks often expose lower_* links.
    # Keep only non-VM-looking stacked devices.
    try:
        lowers = list(base.glob("lower_*"))
        if lowers and not lowered.startswith(("docker", "br-", "cni", "flannel")):
            return True
    except Exception:
        pass

    return False


def iface_metadata(iface):
    base = Path("/sys/class/net") / iface
    return {
        "operstate": read_text(base / "operstate", "-"),
        "carrier": safe_int(read_text(base / "carrier", "0"), 0),
        "speed_mbps": safe_int(read_text(base / "speed", "0"), 0),
        "mtu": safe_int(read_text(base / "mtu", "0"), 0),
        "address": read_text(base / "address", ""),
    }


def bridge_member_ifaces(bridge):
    brif = Path("/sys/class/net") / bridge / "brif"
    if not brif.exists():
        return []
    try:
        return sorted([p.name for p in brif.iterdir()])
    except Exception:
        return []


def collect_physical_network(state, now_ts, interval, health=None, bridge_addresses=None):
    rows = []
    address_map = {
        (str(item.get("role") or "").lower(), str(item.get("bridge") or "")): item
        for item in (bridge_addresses or [])
        if isinstance(item, dict)
    }
    for role, bridge in parse_bridge_roles(BRIDGE_ROLES):
        members = bridge_member_ifaces(bridge)
        if not members:
            bridge_path = Path("/sys/class/net") / bridge
            status = "no_members" if bridge_path.exists() else "not_configured"
            record_bridge_unavailable(health, role, bridge, status)
            continue

        uplinks = [iface for iface in members if is_bridge_member_candidate_uplink(iface)]
        if not uplinks:
            record_bridge_unavailable(health, role, bridge, "no_uplink")
            continue

        for iface in uplinks:
            counters = collect_interface_counters(iface)
            if not counters:
                add_error(health, "cannot read counters for physical iface %s:%s:%s" % (role, bridge, iface))
                continue

            key = "physnet:%s:%s:%s" % (role, bridge, iface)
            old = state.get(key, {})

            rx_delta = delta_counter(counters["rx"], old.get("rx", counters["rx"]))
            tx_delta = delta_counter(counters["tx"], old.get("tx", counters["tx"]))
            rx_packets_delta = delta_counter(counters["rx_packets"], old.get("rx_packets", counters["rx_packets"]))
            tx_packets_delta = delta_counter(counters["tx_packets"], old.get("tx_packets", counters["tx_packets"]))
            rx_drop_delta = delta_counter(counters["rx_drop"], old.get("rx_drop", counters["rx_drop"]))
            tx_drop_delta = delta_counter(counters["tx_drop"], old.get("tx_drop", counters["tx_drop"]))
            rx_error_delta = delta_counter(counters["rx_error"], old.get("rx_error", counters["rx_error"]))
            tx_error_delta = delta_counter(counters["tx_error"], old.get("tx_error", counters["tx_error"]))

            meta = iface_metadata(iface)

            row = {
                "role": role,
                "bridge": bridge,
                "iface": iface,
                "interval_seconds": interval,

                # Deltas for monitor DB/history.
                "rx_delta": rx_delta,
                "tx_delta": tx_delta,
                "rx_packets_delta": rx_packets_delta,
                "tx_packets_delta": tx_packets_delta,
                "rx_drop_delta": rx_drop_delta,
                "tx_drop_delta": tx_drop_delta,
                "rx_error_delta": rx_error_delta,
                "tx_error_delta": tx_error_delta,

                # Absolute counters for debugging.
                "rx_bytes": counters["rx"],
                "tx_bytes": counters["tx"],
                "rx_packets": counters["rx_packets"],
                "tx_packets": counters["tx_packets"],

                # Interface metadata.
                "operstate": meta["operstate"],
                "carrier": meta["carrier"],
                "speed_mbps": meta["speed_mbps"],
                "mtu": meta["mtu"],
                "mac": meta["address"],

                # Addresses live on the Linux bridge itself (br0/br1), not
                # necessarily on the physical member interface.
                "bridge_ipv4": list((address_map.get((role, bridge)) or {}).get("ipv4") or []),
                "bridge_primary_ipv4": str((address_map.get((role, bridge)) or {}).get("primary_ipv4") or ""),
            }

            state[key] = counters
            rows.append(row)

    return rows



def atomic_json_write(path, payload, mode=0o600):
    path = str(path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load_runtime():
    try:
        with open(RUNTIME, "r") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("runtime is not a JSON object")
    except Exception:
        data = {}
    if not isinstance(data.get("carry"), dict):
        data["carry"] = empty_network_window()
    if not isinstance(data.get("iface_map"), dict):
        data["iface_map"] = {}
    if data.get("pending") is not None and not isinstance(data.get("pending"), dict):
        data["pending"] = None
    # Agent v15 derives Consumption on the monitor from the established
    # 5-minute payload. Drop obsolete v14 local 2-hour accumulator state during
    # upgrade so it cannot be retried or grow in runtime.json.
    data.pop("bandwidth_consumption", None)
    return data


def save_runtime(runtime):
    atomic_json_write(RUNTIME, runtime, mode=0o600)


def empty_network_window():
    return {
        "started_at": 0,
        "ended_at": 0,
        "ifaces": {},
        "scan_count": 0,
        "scan_max_ms": 0.0,
    }


def clean_quality(value):
    value = str(value or "NO_DATA").strip().upper()
    return value if value in ("GOOD", "DEGRADED", "POOR", "NO_DATA") else "NO_DATA"


def quality_rank(value):
    return {"NO_DATA": 0, "GOOD": 1, "DEGRADED": 2, "POOR": 3}.get(clean_quality(value), 0)


def quality_from_counts(actual, expected, max_gap):
    actual = max(0, safe_int(actual, 0))
    expected = max(0, safe_int(expected, 0))
    max_gap = max(0.0, safe_float(max_gap, 0.0))
    if actual <= 0 or expected <= 0:
        return "NO_DATA"
    ratio = actual / float(expected)
    if ratio >= 0.90 and max_gap <= SAMPLE_SECONDS * 1.75:
        return "GOOD"
    if ratio >= 0.70 and max_gap <= SAMPLE_SECONDS * 3.0:
        return "DEGRADED"
    return "POOR"


def parse_proc_net_dev(text):
    rows = {}
    for raw in (text or "").splitlines():
        if ":" not in raw:
            continue
        name, values = raw.split(":", 1)
        iface = name.strip()
        fields = values.split()
        if not iface or len(fields) < 16:
            continue
        rows[iface] = {
            "rx": safe_int(fields[0], 0),
            "rx_packets": safe_int(fields[1], 0),
            "rx_error": safe_int(fields[2], 0),
            "rx_drop": safe_int(fields[3], 0),
            "tx": safe_int(fields[8], 0),
            "tx_packets": safe_int(fields[9], 0),
            "tx_error": safe_int(fields[10], 0),
            "tx_drop": safe_int(fields[11], 0),
        }
    return rows


def is_vm_iface_name(iface):
    lowered = str(iface or "").lower()
    return bool(
        lowered.isdigit()
        or lowered.startswith((
            "vnet", "tap", "tun", "fwln", "fwpr", "qvb", "qvo", "qbr"
        ))
    )


def merge_iface_summary(dst, src):
    if not isinstance(dst, dict):
        dst = {}
    if not isinstance(src, dict):
        return dst
    for key in (
        "rx_bytes_sampled", "tx_bytes_sampled",
        "rx_packets_sampled", "tx_packets_sampled",
        "rx_drop_sampled", "tx_drop_sampled",
        "rx_error_sampled", "tx_error_sampled",
        "sample_count", "sample_expected",
        "seconds_over_pps", "seconds_over_mbps",
        "seconds_over_rx_pps", "seconds_over_tx_pps",
        "seconds_over_rx_mbps", "seconds_over_tx_mbps",
    ):
        dst[key] = safe_float(dst.get(key), 0.0) + safe_float(src.get(key), 0.0)
    for key in (
        "rx_mbps_peak", "tx_mbps_peak", "total_mbps_peak",
        "rx_pps_peak", "tx_pps_peak", "total_pps_peak",
        "sample_max_gap_seconds",
    ):
        dst[key] = max(safe_float(dst.get(key), 0.0), safe_float(src.get(key), 0.0))
    dst["first_seen"] = min(
        [x for x in (safe_float(dst.get("first_seen"), 0), safe_float(src.get("first_seen"), 0)) if x > 0]
        or [0]
    )
    dst["last_seen"] = max(safe_float(dst.get("last_seen"), 0), safe_float(src.get("last_seen"), 0))
    dst["sample_quality"] = quality_from_counts(
        dst.get("sample_count"), dst.get("sample_expected"), dst.get("sample_max_gap_seconds")
    )
    return dst


def merge_network_windows(left, right):
    result = empty_network_window()
    left = left if isinstance(left, dict) else {}
    right = right if isinstance(right, dict) else {}
    starts = [safe_int(x, 0) for x in (left.get("started_at"), right.get("started_at")) if safe_int(x, 0) > 0]
    result["started_at"] = min(starts) if starts else 0
    result["ended_at"] = max(safe_int(left.get("ended_at"), 0), safe_int(right.get("ended_at"), 0))
    result["scan_count"] = safe_int(left.get("scan_count"), 0) + safe_int(right.get("scan_count"), 0)
    result["scan_max_ms"] = max(safe_float(left.get("scan_max_ms"), 0), safe_float(right.get("scan_max_ms"), 0))
    for source in (left.get("ifaces") or {}, right.get("ifaces") or {}):
        if not isinstance(source, dict):
            continue
        for iface, summary in source.items():
            result["ifaces"][str(iface)] = merge_iface_summary(result["ifaces"].get(str(iface), {}), summary)
    return result


class NetworkSampler:
    """Bounded in-memory sampler. It never stores a list of individual samples."""

    def __init__(self):
        self.lock = threading.RLock()
        self.last = {}
        self.active = {}
        self.known_ifaces = set()
        self.window_started_mono = time.monotonic()
        self.window_started_wall = int(time.time())
        self.scan_count = 0
        self.scan_max_ms = 0.0

    def update_known_ifaces(self, iface_map):
        with self.lock:
            self.known_ifaces = {str(x) for x in (iface_map or {}) if str(x)}

    def _candidate(self, iface):
        return iface in self.known_ifaces or is_vm_iface_name(iface)

    def sample(self):
        scan_start = time.monotonic()
        now_mono = scan_start
        now_wall = time.time()
        try:
            counters = parse_proc_net_dev(Path("/proc/net/dev").read_text())
        except Exception:
            return False

        with self.lock:
            self.scan_count += 1
            for iface, current in counters.items():
                if not self._candidate(iface):
                    continue
                previous = self.last.get(iface)
                if previous:
                    elapsed = now_mono - safe_float(previous.get("mono"), now_mono)
                    # Ignore an accidental near-simultaneous force sample.
                    if elapsed >= 1.0:
                        rec = self.active.setdefault(iface, {
                            "rx_bytes_sampled": 0,
                            "tx_bytes_sampled": 0,
                            "rx_packets_sampled": 0,
                            "tx_packets_sampled": 0,
                            "rx_drop_sampled": 0,
                            "tx_drop_sampled": 0,
                            "rx_error_sampled": 0,
                            "tx_error_sampled": 0,
                            "rx_mbps_peak": 0.0,
                            "tx_mbps_peak": 0.0,
                            "total_mbps_peak": 0.0,
                            "rx_pps_peak": 0.0,
                            "tx_pps_peak": 0.0,
                            "total_pps_peak": 0.0,
                            "sample_count": 0,
                            "sample_max_gap_seconds": 0.0,
                            "seconds_over_pps": 0.0,
                            "seconds_over_mbps": 0.0,
                            "seconds_over_rx_pps": 0.0,
                            "seconds_over_tx_pps": 0.0,
                            "seconds_over_rx_mbps": 0.0,
                            "seconds_over_tx_mbps": 0.0,
                            "first_seen": safe_float(previous.get("wall"), now_wall),
                            "last_seen": now_wall,
                        })
                        deltas = {}
                        for key in ("rx", "tx", "rx_packets", "tx_packets", "rx_drop", "tx_drop", "rx_error", "tx_error"):
                            deltas[key] = delta_counter(current.get(key), previous.get(key, current.get(key)))
                        rx_mbps = deltas["rx"] * 8.0 / elapsed / 1000000.0
                        tx_mbps = deltas["tx"] * 8.0 / elapsed / 1000000.0
                        rx_pps = deltas["rx_packets"] / elapsed
                        tx_pps = deltas["tx_packets"] / elapsed
                        rec["rx_bytes_sampled"] += deltas["rx"]
                        rec["tx_bytes_sampled"] += deltas["tx"]
                        rec["rx_packets_sampled"] += deltas["rx_packets"]
                        rec["tx_packets_sampled"] += deltas["tx_packets"]
                        rec["rx_drop_sampled"] += deltas["rx_drop"]
                        rec["tx_drop_sampled"] += deltas["tx_drop"]
                        rec["rx_error_sampled"] += deltas["rx_error"]
                        rec["tx_error_sampled"] += deltas["tx_error"]
                        total_mbps = rx_mbps + tx_mbps
                        total_pps = rx_pps + tx_pps
                        rec["rx_mbps_peak"] = max(rec["rx_mbps_peak"], rx_mbps)
                        rec["tx_mbps_peak"] = max(rec["tx_mbps_peak"], tx_mbps)
                        rec["total_mbps_peak"] = max(rec["total_mbps_peak"], total_mbps)
                        rec["rx_pps_peak"] = max(rec["rx_pps_peak"], rx_pps)
                        rec["tx_pps_peak"] = max(rec["tx_pps_peak"], tx_pps)
                        rec["total_pps_peak"] = max(rec["total_pps_peak"], total_pps)
                        rec["sample_count"] += 1
                        rec["sample_max_gap_seconds"] = max(rec["sample_max_gap_seconds"], elapsed)
                        rec["last_seen"] = now_wall
                        if max(rx_pps, tx_pps) >= PPS_WARN > 0:
                            rec["seconds_over_pps"] += elapsed
                        if rx_pps >= PPS_WARN > 0:
                            rec["seconds_over_rx_pps"] += elapsed
                        if tx_pps >= PPS_WARN > 0:
                            rec["seconds_over_tx_pps"] += elapsed
                        if max(rx_mbps, tx_mbps) >= MBPS_WARN > 0:
                            rec["seconds_over_mbps"] += elapsed
                        if rx_mbps >= MBPS_WARN > 0:
                            rec["seconds_over_rx_mbps"] += elapsed
                        if tx_mbps >= MBPS_WARN > 0:
                            rec["seconds_over_tx_mbps"] += elapsed
                current_copy = dict(current)
                current_copy["mono"] = now_mono
                current_copy["wall"] = now_wall
                current_copy["last_seen_mono"] = now_mono
                self.last[iface] = current_copy

            # Bound memory when VM tap names churn over time.
            stale = [
                iface for iface, item in self.last.items()
                if now_mono - safe_float(item.get("last_seen_mono"), now_mono) > STALE_IFACE_SECONDS
            ]
            for iface in stale:
                self.last.pop(iface, None)
                self.active.pop(iface, None)

            scan_ms = (time.monotonic() - scan_start) * 1000.0
            self.scan_max_ms = max(self.scan_max_ms, scan_ms)
        return True

    def rotate(self):
        # Take one near-boundary sample so the 5-minute window is not blurred.
        self.sample()
        now_mono = time.monotonic()
        now_wall = int(time.time())
        with self.lock:
            result = empty_network_window()
            result["started_at"] = self.window_started_wall
            result["ended_at"] = now_wall
            result["scan_count"] = self.scan_count
            result["scan_max_ms"] = round(self.scan_max_ms, 3)
            for iface, rec in self.active.items():
                item = copy.deepcopy(rec)
                first_mono = max(self.window_started_mono, now_mono - max(0.0, now_wall - safe_float(item.get("first_seen"), now_wall)))
                effective = max(0.0, now_mono - first_mono)
                expected = max(1, int(round(effective / float(SAMPLE_SECONDS)))) if effective >= 1 else 1
                item["sample_expected"] = expected
                item["sample_quality"] = quality_from_counts(
                    item.get("sample_count"), expected, item.get("sample_max_gap_seconds")
                )
                result["ifaces"][iface] = item
            self.active = {}
            self.window_started_mono = now_mono
            self.window_started_wall = now_wall
            self.scan_count = 0
            self.scan_max_ms = 0.0
            return result

    def health(self):
        with self.lock:
            return {
                "sample_seconds": SAMPLE_SECONDS,
                "tracked_ifaces": len(self.last),
                "active_ifaces": len(self.active),
                "scan_count": self.scan_count,
                "scan_max_ms": round(self.scan_max_ms, 3),
            }


def sampler_loop(sampler):
    sampler.sample()  # baseline
    deadline = time.monotonic() + SAMPLE_SECONDS
    while not STOP_EVENT.is_set():
        wait = deadline - time.monotonic()
        if wait > 0 and STOP_EVENT.wait(wait):
            break
        if STOP_EVENT.is_set():
            break
        sampler.sample()
        deadline += SAMPLE_SECONDS
        now = time.monotonic()
        # Never run a burst of catch-up scans after overload/suspend.
        if deadline < now:
            deadline = now + SAMPLE_SECONDS


def build_iface_map(rows):
    mapping = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        iface = str(row.get("iface") or "").strip()
        vm_uuid = str(row.get("vm_uuid") or "").strip()
        if not iface or not vm_uuid:
            continue
        mapping[iface] = {
            "vm_uuid": vm_uuid,
            "bridge": str(row.get("bridge") or "-"),
            "mac": str(row.get("mac") or ""),
        }
    return mapping


def collect_network_from_mapping(iface_map, state, health=None):
    rows = []
    for iface, meta in sorted((iface_map or {}).items()):
        if not isinstance(meta, dict):
            continue
        vm_uuid = str(meta.get("vm_uuid") or "").strip()
        if not vm_uuid:
            continue
        counters = collect_interface_counters(iface)
        if not counters:
            continue
        key = "net:%s:%s" % (vm_uuid, iface)
        old = state.get(key, {})
        row = {
            "vm_uuid": vm_uuid,
            "iface": iface,
            "bridge": str(meta.get("bridge") or "-"),
            "mac": str(meta.get("mac") or ""),
            "rx_delta": delta_counter(counters["rx"], old.get("rx", counters["rx"])),
            "tx_delta": delta_counter(counters["tx"], old.get("tx", counters["tx"])),
            "rx_packets_delta": delta_counter(counters["rx_packets"], old.get("rx_packets", counters["rx_packets"])),
            "tx_packets_delta": delta_counter(counters["tx_packets"], old.get("tx_packets", counters["tx_packets"])),
            "rx_drop_delta": delta_counter(counters["rx_drop"], old.get("rx_drop", counters["rx_drop"])),
            "tx_drop_delta": delta_counter(counters["tx_drop"], old.get("tx_drop", counters["tx_drop"])),
            "rx_error_delta": delta_counter(counters["rx_error"], old.get("rx_error", counters["rx_error"])),
            "tx_error_delta": delta_counter(counters["tx_error"], old.get("tx_error", counters["tx_error"])),
        }
        state[key] = counters
        rows.append(row)
    return rows


def hydrate_network_rows(rows, network_window, interval_seconds):
    summaries = (network_window or {}).get("ifaces") or {}
    result = []
    interval_seconds = max(1, safe_int(interval_seconds, PUSH_SECONDS))
    for source in rows or []:
        if not isinstance(source, dict):
            continue
        row = dict(source)
        iface = str(row.get("iface") or "")
        summary = summaries.get(iface) if isinstance(summaries, dict) else None
        summary = summary if isinstance(summary, dict) else {}
        rx_delta = max(0, safe_int(row.get("rx_delta"), 0))
        tx_delta = max(0, safe_int(row.get("tx_delta"), 0))
        rx_packets = max(0, safe_int(row.get("rx_packets_delta"), 0))
        tx_packets = max(0, safe_int(row.get("tx_packets_delta"), 0))
        rx_avg_mbps = rx_delta * 8.0 / interval_seconds / 1000000.0
        tx_avg_mbps = tx_delta * 8.0 / interval_seconds / 1000000.0
        rx_avg_pps = rx_packets / float(interval_seconds)
        tx_avg_pps = tx_packets / float(interval_seconds)
        sample_count = max(0, safe_int(summary.get("sample_count"), 0))
        sample_expected = max(0, safe_int(summary.get("sample_expected"), 0))
        max_gap = max(0.0, safe_float(summary.get("sample_max_gap_seconds"), 0.0))
        quality = clean_quality(summary.get("sample_quality"))
        row.update({
            "interval_seconds": interval_seconds,
            # Peak cannot be lower than the exact whole-window average.
            "rx_mbps_peak": round(max(rx_avg_mbps, safe_float(summary.get("rx_mbps_peak"), 0.0)), 3),
            "tx_mbps_peak": round(max(tx_avg_mbps, safe_float(summary.get("tx_mbps_peak"), 0.0)), 3),
            "total_mbps_peak": round(max(rx_avg_mbps + tx_avg_mbps, safe_float(summary.get("total_mbps_peak"), 0.0)), 3),
            "rx_pps_peak": round(max(rx_avg_pps, safe_float(summary.get("rx_pps_peak"), 0.0)), 3),
            "tx_pps_peak": round(max(tx_avg_pps, safe_float(summary.get("tx_pps_peak"), 0.0)), 3),
            "total_pps_peak": round(max(rx_avg_pps + tx_avg_pps, safe_float(summary.get("total_pps_peak"), 0.0)), 3),
            "rx_packet_size_avg": round(rx_delta / float(rx_packets), 2) if rx_packets > 0 else 0.0,
            "tx_packet_size_avg": round(tx_delta / float(tx_packets), 2) if tx_packets > 0 else 0.0,
            "network_sample_count": sample_count,
            "network_sample_expected": sample_expected,
            "network_sample_max_gap_seconds": round(max_gap, 3),
            "network_sample_quality": quality,
            "pps_warn_threshold": round(PPS_WARN, 3),
            "seconds_over_pps": int(round(max(0.0, safe_float(summary.get("seconds_over_pps"), 0.0)))),
            "seconds_over_mbps": int(round(max(0.0, safe_float(summary.get("seconds_over_mbps"), 0.0)))),
            "seconds_over_rx_pps": int(round(max(0.0, safe_float(summary.get("seconds_over_rx_pps"), 0.0)))),
            "seconds_over_tx_pps": int(round(max(0.0, safe_float(summary.get("seconds_over_tx_pps"), 0.0)))),
            "seconds_over_rx_mbps": int(round(max(0.0, safe_float(summary.get("seconds_over_rx_mbps"), 0.0)))),
            "seconds_over_tx_mbps": int(round(max(0.0, safe_float(summary.get("seconds_over_tx_mbps"), 0.0)))),
        })
        result.append(row)
    return result


def prune_metric_state(state, active_network_keys=None, active_vm_uuids=None, inventory_complete=False):
    if not inventory_complete:
        return
    active_network_keys = set(active_network_keys or [])
    active_vm_uuids = set(active_vm_uuids or [])
    for key in list(state):
        if key.startswith("net:") and key not in active_network_keys:
            state.pop(key, None)
        elif key.startswith("perf:") and key.split(":", 1)[1] not in active_vm_uuids:
            state.pop(key, None)


def collect_cycle_payload(committed_state, runtime, network_window):
    agent_start_mono = time.monotonic()
    now_ts = int(time.time())
    state = copy.deepcopy(committed_state or {})
    last_payload_time = safe_int(state.get("_last_payload_time"), 0)
    interval = now_ts - last_payload_time if last_payload_time > 0 else PUSH_SECONDS
    if interval <= 0:
        interval = PUSH_SECONDS

    health = {
        "version": AGENT_VERSION,
        "started_at": now_ts,
        "duration_ms": 0,
        "timings": {},
        "counts": {},
        "errors": [],
        "notes": [],
        "network_sampler": {
            "sample_seconds": SAMPLE_SECONDS,
            "window_started_at": safe_int((network_window or {}).get("started_at"), 0),
            "window_ended_at": safe_int((network_window or {}).get("ended_at"), 0),
            "scan_count": safe_int((network_window or {}).get("scan_count"), 0),
            "scan_max_ms": safe_float((network_window or {}).get("scan_max_ms"), 0.0),
            "pps_warn": PPS_WARN,
        },
    }

    load1, _load5, _load15 = parse_loadavg()
    load_high = MAX_LOAD > 0 and load1 > MAX_LOAD
    heavy_collection_skipped = bool(load_high and SKIP_HEAVY_ON_OVERLOAD)
    cached_map = runtime.get("iface_map") if isinstance(runtime.get("iface_map"), dict) else {}

    if heavy_collection_skipped:
        add_note(health, "heavy collection limited by explicit setting: load1=%.2f limit=%.2f" % (load1, MAX_LOAD))
        vm_names = sorted({str(x.get("vm_uuid")) for x in cached_map.values() if isinstance(x, dict) and x.get("vm_uuid")})
        inventory_complete = False
        t = time.monotonic()
        interfaces = collect_network_from_mapping(cached_map, state, health=health) if COLLECT_VM_NET else []
        health["timings"]["vm_network_ms"] = ms_since(t)
        vms = []
        health["timings"]["virsh_list_ms"] = 0
        health["timings"]["vm_perf_ms"] = 0
    else:
        if load_high:
            add_note(health, "high load observed with full metrics preserved: load1=%.2f limit=%.2f" % (load1, MAX_LOAD))
        t = time.monotonic()
        vm_names, inventory_complete = get_vm_names(health=health)
        health["timings"]["virsh_list_ms"] = ms_since(t)

        t = time.monotonic()
        interfaces = collect_network(vm_names, state, health=health) if COLLECT_VM_NET else []
        health["timings"]["vm_network_ms"] = ms_since(t)

        t = time.monotonic()
        vms = collect_vm_perf(state, now_ts, health=health) if COLLECT_VM_PERF else []
        health["timings"]["vm_perf_ms"] = ms_since(t)

        new_map = build_iface_map(interfaces)
        if new_map or inventory_complete:
            runtime["iface_map"] = new_map
            cached_map = new_map
        prune_metric_state(
            state,
            active_network_keys={"net:%s:%s" % (row.get("vm_uuid"), row.get("iface")) for row in interfaces if isinstance(row, dict)},
            active_vm_uuids=set(vm_names),
            inventory_complete=inventory_complete,
        )

    interfaces = hydrate_network_rows(interfaces, network_window, interval)

    t = time.monotonic()
    node_host = collect_node_host(state, now_ts, interval) if COLLECT_NODE_HOST else {}
    health["timings"]["node_host_ms"] = ms_since(t)

    t = time.monotonic()
    bridge_addresses = collect_bridge_addresses(health=health)
    health["timings"]["bridge_addresses_ms"] = ms_since(t)

    t = time.monotonic()
    physical_interfaces = collect_physical_network(
        state, now_ts, interval, health=health, bridge_addresses=bridge_addresses
    ) if COLLECT_PHYSICAL_NET else []
    health["timings"]["physical_network_ms"] = ms_since(t)

    state["_last_payload_time"] = now_ts
    health["counts"] = {
        "vm_names": len(vm_names),
        "inventory_complete": 1 if inventory_complete else 0,
        "interfaces": len(interfaces),
        "vms": len(vms),
        "physical_interfaces": len(physical_interfaces),
        "bridge_addresses": len(bridge_addresses),
        "filesystems": len(node_host.get("filesystems", [])) if isinstance(node_host, dict) else 0,
        "network_sampled_interfaces": len((network_window or {}).get("ifaces") or {}),
    }
    health["duration_ms"] = ms_since(agent_start_mono)
    health["overloaded"] = load_high
    health["load_high"] = load_high
    health["heavy_collection_skipped"] = heavy_collection_skipped
    health["load1_at_cycle"] = round(load1, 2)

    payload = {
        "version": AGENT_VERSION,
        "node": NODE_NAME,
        "time": now_ts,
        "interval": interval,
        "interfaces": interfaces,
        "vms": vms,
        "node_host": node_host,
        "vm_inventory": vm_names,
        "inventory_complete": inventory_complete,
        "physical_interfaces": physical_interfaces,
        "bridge_addresses": bridge_addresses,
        "agent_health": health,
        "network_sampler": health["network_sampler"],
    }
    return payload, state


def send_pending(runtime):
    pending = runtime.get("pending")
    if not isinstance(pending, dict):
        return True, None
    payload = pending.get("payload")
    state_after = pending.get("state_after")
    if not isinstance(payload, dict) or not isinstance(state_after, dict):
        runtime["pending"] = None
        save_runtime(runtime)
        return True, None
    response_text = post_payload(payload)
    apply_monitor_config(response_text, runtime)
    save_state(state_after)
    runtime["pending"] = None
    save_runtime(runtime)
    return True, state_after


def run_push_cycle(sampler, runtime, committed_state):
    frozen = sampler.rotate()
    runtime["carry"] = merge_network_windows(runtime.get("carry"), frozen)
    save_runtime(runtime)

    # Retry the exact old payload first. The monitor de-duplicates node+time.
    if isinstance(runtime.get("pending"), dict):
        try:
            _ok, new_state = send_pending(runtime)
            if new_state is not None:
                committed_state = new_state
        except Exception as exc:
            if not QUIET:
                print(
                    "virtinfra-agent ERROR delivery=unavailable stage=retry "
                    "payload_retained=1 detail=%s" % exc,
                    flush=True,
                )
            return committed_state

    payload, state_after = collect_cycle_payload(committed_state, runtime, runtime.get("carry"))
    if DRY_RUN:
        print(json.dumps(payload, indent=2))
        STOP_EVENT.set()
        return committed_state

    # One atomic runtime update moves carry into a durable pending payload.
    # Consumption is derived server-side from this same 5-minute payload.
    runtime["pending"] = {
        "payload": payload,
        "state_after": state_after,
        "created_at": int(time.time()),
    }
    runtime["carry"] = empty_network_window()
    save_runtime(runtime)

    try:
        _ok, new_state = send_pending(runtime)
        if new_state is not None:
            committed_state = new_state
        if not QUIET:
            quality_counts = {}
            for item in payload.get("interfaces") or []:
                quality = clean_quality(item.get("network_sample_quality"))
                quality_counts[quality] = quality_counts.get(quality, 0) + 1

            health = payload.get("agent_health", {}) or {}
            health_details = len(health.get("errors") or [])
            if health.get("heavy_collection_skipped"):
                collection_state = "limited"
            elif health_details:
                collection_state = "partial"
            else:
                collection_state = "complete"

            sample_text = ",".join(
                "%s:%s" % (str(name).lower(), quality_counts[name])
                for name in sorted(quality_counts)
            ) or "none"

            print(
                "virtinfra-agent cycle complete node=%s delivery=ok "
                "interfaces=%s vms=%s host=%s load=%s collection=%s "
                "details=%s samples=%s" % (
                    NODE_NAME,
                    len(payload.get("interfaces") or []),
                    len(payload.get("vms") or []),
                    1 if bool(payload.get("node_host")) else 0,
                    "high" if health.get("overloaded") else "normal",
                    collection_state,
                    health_details,
                    sample_text,
                ),
                flush=True,
            )
    except Exception as exc:
        if not QUIET:
            print(
                "virtinfra-agent ERROR delivery=unavailable stage=current "
                "payload_retained=1 detail=%s" % exc,
                flush=True,
            )

    return committed_state


def next_wall_boundary(now=None):
    now = time.time() if now is None else float(now)
    return (int(now) // PUSH_SECONDS + 1) * PUSH_SECONDS


def handle_signal(_signum, _frame):
    STOP_EVENT.set()

def apply_monitor_config(response_text, runtime):
    """Apply monitor-returned agent config and persist it in runtime.json.

    The monitor returns the current network PPS threshold after every successful
    push. The sampler then uses it for the next complete five-minute window, so
    Admin threshold changes do not require redeploying every node.
    """
    global PPS_WARN
    try:
        payload = json.loads(response_text or "{}")
        cfg = payload.get("agent_config") if isinstance(payload, dict) else None
        if not isinstance(cfg, dict):
            return False
        pps_warn = max(0.0, safe_float(cfg.get("pps_warn"), PPS_WARN))
        revision = max(0, safe_int(cfg.get("revision"), 0))
        PPS_WARN = pps_warn
        runtime["monitor_config"] = {
            "pps_warn": pps_warn,
            "revision": revision,
            "network_enabled": bool(cfg.get("network_enabled", pps_warn > 0)),
            "received_at": int(time.time()),
        }
        save_runtime(runtime)
        return True
    except Exception:
        return False


def restore_monitor_config(runtime):
    global PPS_WARN
    cfg = runtime.get("monitor_config") if isinstance(runtime, dict) else None
    if not isinstance(cfg, dict):
        return
    PPS_WARN = max(0.0, safe_float(cfg.get("pps_warn"), PPS_WARN))


# ---------------------------------------------------------------------------
# HTTP delivery helpers
# ---------------------------------------------------------------------------

def encode_http_payload(payload, allow_gzip=True):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if allow_gzip and HTTP_GZIP and len(raw) >= HTTP_GZIP_MIN_BYTES:
        raw = gzip.compress(raw, compresslevel=1)
        headers["Content-Encoding"] = "gzip"
    return raw, headers


def post_json_payload(url, payload, user_agent):
    data, encoding_headers = encode_http_payload(payload, allow_gzip=True)

    def send(body, extra_headers):
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                **extra_headers,
                "X-Token": TOKEN,
                "User-Agent": user_agent,
            },
        )
        return urllib.request.urlopen(req, timeout=API_TIMEOUT).read().decode()

    try:
        return send(data, encoding_headers)
    except urllib.error.HTTPError as exc:
        # Rolling upgrades and rollback remain safe: older monitors do not
        # understand request Content-Encoding and normally answer 400/415.
        if encoding_headers.get("Content-Encoding") == "gzip" and exc.code in (400, 415):
            plain, plain_headers = encode_http_payload(payload, allow_gzip=False)
            return send(plain, plain_headers)
        raise


def post_payload(payload):
    return post_json_payload(API, payload, "VirtInfra-Agent/15")


def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    runtime = load_runtime()
    restore_monitor_config(runtime)
    committed_state = load_state()
    sampler = NetworkSampler()
    sampler.update_known_ifaces(runtime.get("iface_map") or {})
    thread = threading.Thread(target=sampler_loop, args=(sampler,), name="virtinfra-agent-net", daemon=True)
    thread.start()

    # Give the sampler a baseline, then publish current heavy metrics immediately.
    STOP_EVENT.wait(0.5)
    committed_state = run_push_cycle(sampler, runtime, committed_state)
    sampler.update_known_ifaces(runtime.get("iface_map") or {})

    boundary = next_wall_boundary()
    while not STOP_EVENT.is_set():
        wait = max(0.0, boundary - time.time())
        if STOP_EVENT.wait(wait):
            break
        committed_state = run_push_cycle(sampler, runtime, committed_state)
        sampler.update_known_ifaces(runtime.get("iface_map") or {})
        boundary += PUSH_SECONDS
        now = time.time()
        if boundary <= now:
            boundary = next_wall_boundary(now)

    # Preserve the partial network window on a graceful stop without creating a push.
    try:
        frozen = sampler.rotate()
        runtime["carry"] = merge_network_windows(runtime.get("carry"), frozen)
        save_runtime(runtime)
    except Exception:
        pass
    thread.join(timeout=2)


if __name__ == "__main__":
    main()
