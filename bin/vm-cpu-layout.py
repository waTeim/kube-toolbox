#!/usr/bin/env python
"""
vm_pin_xml.py

Generate paste-ready libvirt XML for CPU pinning, based on REAL topology:
- Reads NUMA layout (numactl -H)
- Reads SMT siblings (/sys/.../thread_siblings_list)
- Emits <vcpupin> and <emulatorpin> with correct sibling IDs (no contiguity assumptions)
- Supports multiple VMs in one go, avoiding overlaps

Usage examples:

# VM 'node0' on socket 0: 12 vCPUs using both threads (12 cores * 2)
./vm_pin_xml.py \
  --vm node0:socket=0,mode=smt,vcpus=24,emu=8 \
  --vm node12:socket=1,mode=core,vcpus=12,emu=12

# Full socket by threads on socket 1 (24 cores * 2 = 48 vCPUs)
./vm_pin_xml.py --vm dbA:socket=1,mode=smt,vcpus=48

# Half the cores on socket 1 (12 vCPUs, one thread per core)
./vm_pin_xml.py --vm api1:socket=1,mode=core,vcpus=12

Notes:
- mode=core  → vcpus = #cores you want (one thread/core)
- mode=smt   → vcpus must be EVEN (two threads/core)
- emu=N      → optional emulator span size (default 12)
"""

import argparse, os, subprocess, sys
from typing import Dict, List, Set, Tuple

def sh(cmd: List[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        print(e.output, file=sys.stderr)
        sys.exit(1)

def parse_numactl() -> Dict[int, List[int]]:
    nodes: Dict[int, List[int]] = {}
    for line in sh(["numactl", "-H"]).splitlines():
        line = line.strip()
        if line.startswith("node ") and "cpus:" in line:
            parts = line.split()
            nid = int(parts[1]); idx = parts.index("cpus:")
            nodes[nid] = [int(x) for x in parts[idx+1:]]
    if not nodes:
        sys.exit("Failed to parse NUMA nodes from numactl -H")
    return nodes

def parse_thread_siblings() -> Dict[int, List[int]]:
    """
    Returns {cpu: sorted(list_of_all_threads_on_same_core)}.
    Handles tokens like '0,48' and '0-3,48-51'.
    """
    base = "/sys/devices/system/cpu"
    raw: Dict[int, Set[int]] = {}

    def expand(token: str) -> List[int]:
        token = token.strip()
        if not token: return []
        if "-" in token:
            a, b = token.split("-", 1)
            return list(range(int(a), int(b) + 1))
        return [int(token)]

    for name in os.listdir(base):
        if not name.startswith("cpu"): continue
        try:
            cid = int(name[3:])
        except ValueError:
            continue
        p = os.path.join(base, name, "topology", "thread_siblings_list")
        if not os.path.exists(p): continue
        txt = open(p).read().strip()
        members: List[int] = []
        for part in txt.split(","):
            members.extend(expand(part))
        raw[cid] = set(members)

    # Make symmetric and sort
    for c, s in list(raw.items()):
        for x in s:
            raw.setdefault(x, set()).add(c)

    siblings: Dict[int, List[int]] = {c: sorted(s) for c, s in raw.items()}
    if not siblings:
        sys.exit("Failed to parse thread_siblings_list (no SMT info?)")
    return siblings

def primary_threads(node_cpus: List[int], siblings: Dict[int, List[int]]) -> List[int]:
    """
    Choose one representative (lowest id) per core on a node.
    """
    seen: Set[int] = set()
    prim: List[int] = []
    for cpu in sorted(node_cpus):
        if cpu in seen: continue
        core = siblings.get(cpu, [cpu])
        for t in core: seen.add(t)
        prim.append(min(core))
    return prim

def sibling_of(primary: int, siblings: Dict[int, List[int]]) -> int:
    core = siblings.get(primary, [primary])
    # return any other thread on that core; prefer the next larger id if present
    if len(core) >= 2:
        return core[1] if core[0] == primary else core[0]
    return primary  # no SMT

def take(n: int, items: List[int]) -> List[int]:
    if len(items) < n:
        raise ValueError(f"Need {n} ids, only have {len(items)}")
    return items[:n]

def choose_emulator_slice(node_free: List[int], span: int) -> List[int]:
    """
    Pick a contiguous-looking slice if possible; otherwise first span CPUs.
    (We don’t assume specific patterns; we just take what's free deterministically.)
    """
    if len(node_free) < span:
        raise ValueError(f"Not enough free CPUs for emulator span={span} (have {len(node_free)})")
    return node_free[:span]

def build_vm_plan(
    vm_name: str,
    node_id: int,
    mode: str,
    vcpus: int,
    emu_span: int,
    nodes: Dict[int, List[int]],
    siblings: Dict[int, List[int]],
    reserved: Set[int],
) -> Tuple[str, Set[int]]:
    """
    Returns (xml_block, used_cpu_ids). If emu_span == 0, we omit <emulatorpin>.
    """
    node_all = sorted([c for c in nodes[node_id] if c not in reserved])
    if not node_all:
        raise ValueError(f"No available CPUs on node {node_id} for {vm_name}")

    primaries = [p for p in primary_threads(node_all, siblings) if p not in reserved]

    vcpu_map: List[Tuple[int, int]] = []  # (vcpu_index, host_cpu_id)
    used: Set[int] = set()

    if mode == "core":
        # one thread per core: vcpus == number of cores you want
        chosen_prim = take(vcpus, primaries)
        for i, p in enumerate(chosen_prim):
            vcpu_map.append((i, p)); used.add(p)
    elif mode == "smt":
        if vcpus % 2 != 0:
            raise ValueError(f"{vm_name}: mode=smt requires an even vcpus, got {vcpus}")
        cores_needed = vcpus // 2
        chosen_prim = take(cores_needed, primaries)
        # first half → primaries
        for i, p in enumerate(chosen_prim):
            vcpu_map.append((i, p)); used.add(p)
        # second half → actual siblings
        for i, p in enumerate(chosen_prim):
            s = sibling_of(p, siblings)
            vcpu_map.append((cores_needed + i, s)); used.add(s)
    else:
        raise ValueError(f"Unknown mode {mode} (use 'core' or 'smt')")

    # Emulator: same node, avoid used; skip entirely if emu_span == 0
    emu: List[int] = []
    if emu_span > 0:
        node_free = [c for c in node_all if c not in used]
        if len(node_free) < emu_span:
            raise ValueError(f"Not enough free CPUs on node {node_id} for emulator span {emu_span}")
        emu = node_free[:emu_span]
        used.update(emu)

    # Emit XML
    lines: List[str] = []
    lines.append(f"<!-- {vm_name}: node={node_id}, mode={mode}, vcpus={vcpus} -->")
    lines.append(f"<vcpu placement='static'>{vcpus}</vcpu>")
    lines.append("<cputune>")
    for v, p in sorted(vcpu_map):
        lines.append(f"    <vcpupin vcpu='{v}' cpuset='{p}'/>")
    if emu:  # only emit when emu_span > 0
        emu_str = f"{min(emu)}-{max(emu)}" if len(emu) > 1 else str(emu[0])
        lines.append(f"    <emulatorpin cpuset='{emu_str}'/>")
    lines.append("</cputune>")
    lines.append("<numatune>")
    lines.append(f"  <memory mode='preferred' nodeset='{node_id}'/>")
    lines.append("</numatune>")
    xml = "\n".join(lines)
    return xml, used


def parse_vm_arg(arg: str) -> dict:
    """
    --vm NAME:socket=1,mode=smt,vcpus=24,emu=12
    """
    if ":" not in arg:
        raise ValueError("VM spec must be NAME:key=val,...")
    name, rest = arg.split(":", 1)
    opts = {"name": name}
    for kv in rest.split(","):
        if not kv: continue
        if "=" not in kv:
            raise ValueError(f"Bad vm option '{kv}' in '{arg}'")
        k, v = kv.split("=", 1)
        opts[k.strip()] = v.strip()
    # normalize types
    try:
        opts["socket"] = int(opts["socket"])
    except Exception:
        raise ValueError(f"{name}: missing/invalid socket (expected 0 or 1)")
    opts["mode"] = opts.get("mode", "core")
    try:
        opts["vcpus"] = int(opts["vcpus"])
    except Exception:
        raise ValueError(f"{name}: missing/invalid vcpus (int)")
    opts["emu"] = int(opts.get("emu", 12))
    return opts

def main():
    ap = argparse.ArgumentParser(description="Emit libvirt XML CPU pinning based on real topology.")
    ap.add_argument(
        "--vm",
        action="append",
        required=True,
        help=(
            "VM spec: NAME:socket=<0|1>,mode=<core|smt>,vcpus=<int>,emu=<int>\n"
            "  emu = number of host CPUs to reserve for <emulatorpin>; use 0 to omit"
        )
    )

    args = ap.parse_args()

    nodes = parse_numactl()
    siblings = parse_thread_siblings()

    reserved: Set[int] = set()
    outputs: List[str] = []

    for spec in args.vm:
        cfg = parse_vm_arg(spec)
        name = cfg["name"]; socket = cfg["socket"]; mode = cfg["mode"]; vcpus = cfg["vcpus"]; emu = cfg["emu"]
        if socket not in nodes:
            raise SystemExit(f"{name}: socket/NUMA node {socket} not present on this host")
        xml, used = build_vm_plan(name, socket, mode, vcpus, emu, nodes, siblings, reserved)
        reserved |= used
        outputs.append(xml)

    # Print all blocks
    sep = "\n" + ("-" * 72) + "\n"
    print(sep.join(outputs))

if __name__ == "__main__":
    main()
