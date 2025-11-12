#!/usr/bin/env python3
import argparse, subprocess, json, re, sys, shutil
from math import isfinite

# Known TBW ratings (decimal TB). Extend as you like.
KNOWN_TBW_TB = {
    "samsung ssd 870 evo 2tb": 1200.0,
}

def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout

def storcli_path():
    return shutil.which("storcli64") or "/opt/MegaRAID/storcli/storcli64"

def list_dids_json(ctrl: int):
    """Try to list DIDs using StorCLI JSON output."""
    sc = storcli_path()
    # JSON is more reliable without 'all'
    out = run([sc, f"/c{ctrl}", "/eall", "/sall", "show", "J"])
    try:
        j = json.loads(out)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\})", out, re.S)
        if not m:
            return []
        j = json.loads(m.group(1))
    dids = set()
    # Walk for any table rows having 'DID'
    def walk(o):
        if isinstance(o, dict):
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for it in o: walk(it)
        else:
            pass
        if isinstance(o, list):
            for row in o:
                if isinstance(row, dict) and "DID" in row:
                    did = row.get("DID")
                    if isinstance(did, int) or (isinstance(did, str) and did.isdigit()):
                        dids.add(int(did))
    walk(j)
    return sorted(dids)

def list_dids_text(ctrl: int):
    """Fallback: parse text table from StorCLI."""
    sc = storcli_path()
    out = run([sc, f"/c{ctrl}", "/eall", "/sall", "show"])
    dids = set()
    # Lines like: "252:0     6 UGood  -  1.818 TB SATA ..."
    for line in out.splitlines():
        m = re.match(r"\s*\d+:\d+\s+(\d+)\s+\S+", line)
        if m:
            dids.add(int(m.group(1)))
    return sorted(dids)

def list_dids(ctrl: int):
    dids = list_dids_json(ctrl)
    if not dids:
        dids = list_dids_text(ctrl)
    return dids

def probe_smart(osdev: str, did: int) -> str:
    """Prefer sat+megaraid for SATA; fall back to megaraid."""
    for dtype in (f"sat+megaraid,{did}", f"megaraid,{did}"):
        try:
            return run(["smartctl", "-a", "-d", dtype, osdev])
        except subprocess.CalledProcessError as e:
            last = e.stdout
    raise RuntimeError(f"smartctl failed for DID {did}.\n{last}")

def parse_field(pattern: str, text: str, flags=re.M):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None

def parse_int_attr(attr_id: int, name: str, text: str):
    # Match a SMART attribute row: ID  Name  ... RAW_VALUE
    pat = rf"^\s*{attr_id}\s+{re.escape(name)}\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+-\s+(\d+)"
    v = parse_field(pat, text)
    return int(v) if v and v.isdigit() else None

def lbas_to_tib(lbas: int) -> float:
    return (lbas * 512.0) / (1024.0**4)

def tbw_percent(model: str | None, tib_written: float, override_tbw_tb: float | None):
    model_l = (model or "").lower()
    tbw_tb = override_tbw_tb
    if not tbw_tb:
        for key, val in KNOWN_TBW_TB.items():
            if key in model_l:
                tbw_tb = val
                break
    if tbw_tb and tbw_tb > 0:
        tib_per_tb = (1000.0**4) / (1024.0**4)  # 1 TB (decimal) in TiB
        pct = (tib_written / (tbw_tb * tib_per_tb)) * 100.0
        return tbw_tb, pct
    return None, None

def summarize(osdev: str, did: int, tbw_override: float | None, raw: bool):
    try:
        txt = probe_smart(osdev, did)
    except Exception as e:
        print(f"{did:>5}  ERROR: {e}")
        return

    model  = parse_field(r"Device Model:\s+(.+)", txt)
    serial = parse_field(r"Serial Number:\s+(.+)", txt)
    poh    = parse_int_attr(9,   "Power_On_Hours",       txt) or 0
    wear   = parse_int_attr(177, "Wear_Leveling_Count",  txt)
    rsvd   = parse_int_attr(179, "Used_Rsvd_Blk_Cnt_Tot",txt)
    lba_w  = parse_int_attr(241, "Total_LBAs_Written",   txt) or 0
    lba_r  = parse_int_attr(242, "Total_LBAs_Read",      txt) or 0

    tw = lbas_to_tib(lba_w)
    tr = lbas_to_tib(lba_r)
    tbw_tb, pct = tbw_percent(model, tw, tbw_override)

    tbw_str = f"{tbw_tb:.0f}" if tbw_tb else "-"
    pct_str = f"{pct:6.1f}%" if (pct is not None and isfinite(pct)) else "   -   "

    print(f"{did:>5}  { (model or '?')[:35]:35} { (serial or '?')[:17]:17} {poh:>4} "
          f"{wear if wear is not None else '-':>8} {rsvd if rsvd is not None else '-':>8} "
          f"{tw:12.2f} {tr:11.2f} {tbw_str:>7}  {pct_str}")

    if raw:
        print("\n---- raw smartctl ----\n" + txt.strip() + "\n----------------------\n")

def main():
    ap = argparse.ArgumentParser(description="SSD wear summary via smartctl (MegaRAID passthrough)")
    ap.add_argument("--controller", "-c", type=int, default=0, help="MegaRAID controller index (default: 0)")
    ap.add_argument("--osdev", "-d", default="/dev/sda", help="Any OS device on the same controller (default: /dev/sda)")
    ap.add_argument("--did", nargs="*", type=int, help="One or more MegaRAID Device IDs to query")
    ap.add_argument("--all", action="store_true", help="Query all DIDs discovered via StorCLI")
    ap.add_argument("--tbw", type=float, help="Rated TBW (TB, decimal) to compute %% used (overrides heuristic)")
    ap.add_argument("--raw", action="store_true", help="Also print raw smartctl output per DID")
    args = ap.parse_args()

    if not shutil.which("smartctl"):
        sys.exit("smartctl not found. Install smartmontools first.")

    if not shutil.which("storcli64") and not shutil.which("/opt/MegaRAID/storcli/storcli64"):
        print("# Warning: storcli64 not found on PATH; falling back to default path /opt/MegaRAID/storcli/storcli64", file=sys.stderr)

    if args.all:
        dids = list_dids(args.controller)
        if not dids:
            sys.exit("No DIDs found via StorCLI.")
    elif args.did:
        dids = args.did
    else:
        ap.print_help()
        sys.exit(1)

    print(f"# Controller c{args.controller} | OS dev: {args.osdev}")
    print("# DID  Model                              Serial            POH  Wear177  Rsvd179  Written(TiB)  Read(TiB)   TBW(TB)  %LifeUsed")
    print("# ---- ----------------------------------- ----------------- ---- -------- -------- ------------ ----------- -------  ----------")

    for did in dids:
        summarize(args.osdev, did, args.tbw, args.raw)

if __name__ == "__main__":
    main()
