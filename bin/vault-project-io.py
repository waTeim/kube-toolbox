#!/usr/bin/env python3
"""
projects_io.py
──────────────────────
Store/retrieve MULTIPLE files in KV v2 at <mount>/data/<user>/<project>.

Secret shape (KV v2 "data"):
  { "files": {
      "config.yaml": { "filename": "config.yaml", "encoding": "base64", "size_bytes": 123, "sha256": "...", "mime": "text/yaml", "bytes": "..." },
      "server.crt":  { ... }
  }}

Commands:
  push <FILE...>        Add/update one or more files
  pull [--dir DIR]      Restore all files to DIR (defaults to .)
  list-projects         List projects under the current user (via metadata LIST)
  ls                    List filenames in the current project
  cat <NAME>            Print a stored file to stdout (UTF-8 if possible)
  rm <NAME...>          Remove one or more stored files
  mv <OLD> <NEW>        Rename a stored file

  delete [--soft|--destroy --versions ...]
  undelete [--versions ...]

Auth resolution order:
  1) --vault-token
  2) $AUTH / $VAULT_TOKEN
  3) ~/.vault-token
  4) `vault login -method=oidc`  (if --login-oidc or as last resort)

Owner:
  By default derived from your token (personal alias).
  Use -g/--group to target a shared group.

Paths:
  Stored filenames are the file paths relative to the current working directory.
  Subdirectories are preserved (e.g., "cfg/app.yaml"). Absolute paths and ".." are rejected.
"""

import argparse, base64, hashlib, json, mimetypes, os, sys, subprocess, urllib.error, urllib.request
from urllib.parse import quote

# ------------------------------- HTTP / Vault helpers -------------------------------

def vault_request(addr, token, method, path, data=None, *, allow_404=False):
    url = addr.rstrip("/") + "/v1/" + path.lstrip("/")
    req = urllib.request.Request(url, method=method)
    req.add_header("X-Vault-Token", token)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
        req.data = body
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        if allow_404 and e.code == 404:
            return {"_missing": True}
        msg = e.read().decode("utf-8", errors="ignore")
        raise SystemExit(f"[ERROR] {method} {url} -> HTTP {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[ERROR] {method} {url} -> {e}")

def read_token_from_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            t = f.read().strip()
            return t if t else None
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[WARN] Could not read token file {path}: {e}", file=sys.stderr)
        return None

def run_vault_login_oidc(addr):
    env = os.environ.copy()
    env["VAULT_ADDR"] = addr
    try:
        proc = subprocess.run(
            ["vault", "login", "-method=oidc", "-format=json"],
            check=False, capture_output=True, text=True, env=env
        )
    except FileNotFoundError:
        raise SystemExit("[FATAL] vault CLI not found in PATH, and no token provided.")
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise SystemExit(f"[FATAL] `vault login -method=oidc` failed: {msg}")
    try:
        obj = json.loads(proc.stdout)
        token = obj.get("auth", {}).get("client_token")
        if not token:
            raise ValueError("missing auth.client_token")
        return token
    except Exception as e:
        raise SystemExit(f"[FATAL] Could not parse login JSON: {e}\nOutput was:\n{proc.stdout}")

def resolve_token(cli_token: str | None, *, force_oidc: bool, addr: str):
    if cli_token:
        return cli_token
    if force_oidc:
        print("[INFO] Forcing OIDC login via `vault login -method=oidc`...", file=sys.stderr)
        return run_vault_login_oidc(addr)
    for envvar in ("AUTH", "VAULT_TOKEN"):
        t = os.getenv(envvar)
        if t:
            return t
    t = read_token_from_file(os.path.expanduser("~/.vault-token"))
    if t:
        return t
    print("[INFO] No token via flag/ENV/file; invoking `vault login -method=oidc`...", file=sys.stderr)
    return run_vault_login_oidc(addr)

def discover_id(addr, token):
    info = vault_request(addr, token, "GET", "auth/token/lookup-self")
    data = info.get("data", {})
    meta = data.get("meta", {}) or {}
    username = meta.get("username") or meta.get("user") or None
    if username:
        return username
    dn = data.get("display_name") or ""
    if dn.startswith("oidc-") and len(dn) > 5:
        return dn[5:]
    raise SystemExit("[FATAL] Could not derive user id from token (no meta.username/user and display_name not oidc-*).")

def kv_path(mount: str, owner: str, project: str | None, *, kind: str):
    """
    kind ∈ { data, metadata, delete, undelete, destroy }
    """
    mp = mount.strip("/")
    safe_owner = quote(owner, safe="")
    safe_proj = quote(project, safe="") if project is not None else ""
    if kind not in ("data", "metadata", "delete", "undelete", "destroy"):
        raise ValueError("kind must be data|metadata|delete|undelete|destroy")
    return f"{mp}/{kind}/{safe_owner}/{safe_proj}" if safe_proj else f"{mp}/{kind}/{safe_owner}"

# ------------------------------- Blob helpers -------------------------------

def _file_to_record(path_fs: str, stored_name: str):
    with open(path_fs, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    sha = hashlib.sha256(raw).hexdigest()
    mime, _ = mimetypes.guess_type(stored_name)
    return {
        "filename": stored_name,             # may include subdirs like "cfg/app.yaml"
        "encoding": "base64",
        "size_bytes": len(raw),
        "sha256": sha,
        "mime": mime or "application/octet-stream",
        "bytes": b64,
    }

def _record_to_bytes(rec: dict) -> bytes:
    if not isinstance(rec, dict) or rec.get("encoding") != "base64" or "bytes" not in rec:
        raise SystemExit("[FATAL] Secret content is not a blob record with base64 'bytes'.")
    data = base64.b64decode(rec["bytes"])
    if "sha256" in rec:
        sha = hashlib.sha256(data).hexdigest()
        if sha != rec["sha256"]:
            raise SystemExit(f"[FATAL] SHA256 mismatch: expected {rec['sha256']}, got {sha}")
    return data

def _record_to_file(rec: dict, out_dir: str | None = None):
    data = _record_to_bytes(rec)
    fname = rec.get("filename") or "blob.bin"  # can contain "a/b/c.txt"
    tgt_dir = os.path.abspath(out_dir or ".")
    out_path = os.path.join(tgt_dir, fname)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path, len(data)

def _safe_relname(name: str) -> str:
    # normalize and forbid absolute/parent escapes
    n = os.path.normpath(name).replace("\\", "/")
    if os.path.isabs(name) or n == ".." or n.startswith("../"):
        raise SystemExit(f"[FATAL] Unsafe path '{name}'")
    return n

# ------------------------------- Project data helpers -------------------------------

def _read_project(addr, token, mount, owner, project):
    path = kv_path(mount, owner, project, kind="data")
    resp = vault_request(addr, token, "GET", path, allow_404=True)
    if resp.get("_missing"):
        return True, {}, {}
    data = resp.get("data", {}) or {}
    files = data.get("data", {}).get("files", {})
    if not isinstance(files, dict):
        files = {}
    return False, files, resp

def _write_project(addr, token, mount, owner, project, files_map: dict):
    path = kv_path(mount, owner, project, kind="data")
    payload = {"data": {"files": files_map}}
    return vault_request(addr, token, "POST", path, data=payload)

def _get_current_version(addr, token, mount, owner, project):
    meta_path = kv_path(mount, owner, project, kind="metadata")
    resp = vault_request(addr, token, "GET", meta_path, allow_404=True)
    if resp.get("_missing"):
        return None, {}
    d = resp.get("data", {}) or {}
    return d.get("current_version"), d

# ------------------------------- Commands -------------------------------

def cmd_push(addr, token, mount, owner, project, file_paths, warn_threshold=900_000):
    if not file_paths:
        raise SystemExit("[FATAL] push requires at least one FILE.")
    missing, current_files, _ = _read_project(addr, token, mount, owner, project)

    cwd = os.getcwd()
    added = []
    for p in file_paths:
        if not os.path.isfile(p):
            raise SystemExit(f"[FATAL] Not a file: {p}")
        abs_path = os.path.abspath(p)
        rel = os.path.relpath(abs_path, cwd)
        stored = _safe_relname(rel)
        rec = _file_to_record(abs_path, stored)
        if rec["size_bytes"] > warn_threshold:
            print(f"[WARN] {rec['filename']}: {rec['size_bytes']} bytes. KV v2 is for small secrets.", file=sys.stderr)
        current_files[rec["filename"]] = rec
        added.append(rec["filename"])

    resp = _write_project(addr, token, mount, owner, project, current_files)
    ver = resp.get("data", {}).get("version")
    status = "created" if missing else "updated"
    print(f"[OK] {status} project '{project}' with {len(added)} file(s): {', '.join(added)} (version={ver})")


def cmd_pull(addr, token, mount, owner, project, out_dir):
    missing, files_map, _ = _read_project(addr, token, mount, owner, project)
    if missing or not files_map:
        print("[INFO] Nothing stored for this project yet.")
        return
    total = 0
    for _, rec in files_map.items():
        out_path, size = _record_to_file(rec, out_dir)
        print(f"[OK] Wrote {size} bytes to {out_path}")
        total += 1
    print(f"[OK] Restored {total} file(s) to {os.path.abspath(out_dir or '.')}")

def cmd_list_projects(addr, token, mount, owner):
    mp = mount.strip("/")
    safe_owner = quote(owner, safe="")
    resp = vault_request(addr, token, "LIST", f"{mp}/metadata/{safe_owner}", allow_404=True)
    if resp.get("_missing"):
        print("(no projects)")
        return
    keys = resp.get("data", {}).get("keys", []) or []
    cleaned = sorted(k[:-1] if k.endswith("/") else k for k in keys)
    if not cleaned:
        print("(no projects)")
        return
    for k in cleaned:
        print(k)

def cmd_delete(addr, token, mount, owner, project, *, soft=False, destroy=False, versions=None, force=False):
    if soft and destroy:
        raise SystemExit("[FATAL] Choose either --soft or --destroy, not both.")

    if soft or destroy:
        cur, _ = _get_current_version(addr, token, mount, owner, project)
        if versions is None or versions == []:
            if soft:
                versions = [cur] if cur else []
            else:
                raise SystemExit("[FATAL] --destroy requires --versions N[,M,…].")
        try:
            versions = [int(v) for v in versions]
        except Exception:
            raise SystemExit("[FATAL] versions must be integers.")

    action = (
        "purge ALL versions + metadata"
        if not (soft or destroy)
        else ("soft-delete versions " + ",".join(map(str, versions)) if soft else "DESTROY versions " + ",".join(map(str, versions)))
    )
    target = f"{mount.strip('/')}/{owner}/{project or ''}"
    if not force:
        ans = input(f"About to {action} at {target}. Proceed? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("[INFO] Aborted.")
            return

    if soft:
        path = kv_path(mount, owner, project, kind="delete")
        vault_request(addr, token, "POST", path, data={"versions": versions})
        print(f"[OK] Soft-deleted versions {versions} at {target}.")
    elif destroy:
        path = kv_path(mount, owner, project, kind="destroy")
        vault_request(addr, token, "POST", path, data={"versions": versions})
        print(f"[OK] Permanently destroyed versions {versions} at {target}.")
    else:
        meta_path = kv_path(mount, owner, project, kind="metadata")
        vault_request(addr, token, "DELETE", meta_path, data=None)
        print(f"[OK] Purged project '{project}' (all versions + metadata removed) at {target}.")

def cmd_undelete(addr, token, mount, owner, project, versions=None, force=False):
    cur, _ = _get_current_version(addr, token, mount, owner, project)
    if versions is None or versions == []:
        if not cur:
            print("[INFO] No versions found to undelete.")
            return
        versions = [cur]
    try:
        versions = [int(v) for v in versions]
    except Exception:
        raise SystemExit("[FATAL] versions must be integers.")
    target = f"{mount.strip('/')}/{owner}/{project or ''}"
    if not force:
        ans = input(f"About to UNDELETE versions {versions} at {target}. Proceed? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("[INFO] Aborted.")
            return
    path = kv_path(mount, owner, project, kind="undelete")
    vault_request(addr, token, "POST", path, data={"versions": versions})
    print(f"[OK] Undeleted versions {versions} at {target}.")

# -------- per-file commands --------

def cmd_ls(addr, token, mount, owner, project):
    missing, files_map, _ = _read_project(addr, token, mount, owner, project)
    if missing:
        print("(project not found)")
        return
    if not files_map:
        print("(no files)")
        return
    for name in sorted(files_map.keys()):
        print(name)

def cmd_cat(addr, token, mount, owner, project, name):
    missing, files_map, _ = _read_project(addr, token, mount, owner, project)
    if missing or name not in files_map:
        raise SystemExit(f"[FATAL] File '{name}' not found in project '{project}'.")
    rec = files_map[name]
    data = _record_to_bytes(rec)
    try:
        sys.stdout.write(data.decode("utf-8"))
    except UnicodeDecodeError:
        b64 = base64.b64encode(data).decode("ascii")
        print(f"[INFO] '{name}' is not valid UTF-8; printing base64 below:\n{b64}")

def cmd_rm(addr, token, mount, owner, project, names):
    if not names:
        raise SystemExit("[FATAL] rm requires at least one NAME.")
    missing, files_map, _ = _read_project(addr, token, mount, owner, project)
    if missing:
        raise SystemExit(f"[FATAL] Project '{project}' does not exist.")
    removed = []
    for n in names:
        if n in files_map:
            del files_map[n]
            removed.append(n)
        else:
            print(f"[WARN] '{n}' not found; skipping.", file=sys.stderr)
    if not removed:
        print("[INFO] Nothing to remove.")
        return
    _write_project(addr, token, mount, owner, project, files_map)
    print(f"[OK] Removed {len(removed)} file(s): {', '.join(removed)}")

def cmd_mv(addr, token, mount, owner, project, old, new):
    if old == new:
        print("[INFO] mv: old and new names are the same; nothing to do.")
        return
    missing, files_map, _ = _read_project(addr, token, mount, owner, project)
    if missing or old not in files_map:
        raise SystemExit(f"[FATAL] File '{old}' not found in project '{project}'.")
    if new in files_map:
        raise SystemExit(f"[FATAL] Target name '{new}' already exists.")
    rec = files_map.pop(old)
    rec["filename"] = new
    files_map[new] = rec
    _write_project(addr, token, mount, owner, project, files_map)
    print(f"[OK] Renamed '{old}' -> '{new}'")

# ------------------------------- CLI -------------------------------

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    # global args
    p.add_argument("--vault-addr", default=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"))
    p.add_argument("--vault-token", default=None, help="Explicit Vault token (overrides all other sources)")
    p.add_argument("--login-oidc", action="store_true", help="Force OIDC login via `vault login -method=oidc`")
    p.add_argument("--mount-path", default="projects", help="KV v2 mount path (no trailing slash)")
    p.add_argument("--project", default="default", help="Project key under the selected owner (user or group)")
    p.add_argument("-g", "--group", dest="group", default=None, help="Operate in a shared group (e.g., 'g0'). If omitted, uses your personal alias from the token.")

    # bulk file
    sp_push = sub.add_parser("push", help="Push one or more files to KV v2 (merge by filename)")
    sp_push.add_argument("files", nargs="+", help="Path(s) to file(s) to store")

    sp_pull = sub.add_parser("pull", help="Pull all stored files, writing to their original filenames")
    sp_pull.add_argument("--dir", default=".", help="Directory to write files into (default: current dir)")

    sub.add_parser("list-projects", help="List the owner's project names")

    sp_del = sub.add_parser("delete", help="Delete a project (purge by default)")
    g = sp_del.add_mutually_exclusive_group()
    g.add_argument("--soft", action="store_true", help="Soft-delete versions (default: current version)")
    g.add_argument("--destroy", action="store_true", help="Permanently destroy specific versions (requires --versions)")
    sp_del.add_argument("--versions", help="Comma-separated versions for --soft/--destroy (default for --soft: current version)")
    sp_del.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    sp_und = sub.add_parser("undelete", help="Undelete soft-deleted versions (default: current_version)")
    sp_und.add_argument("--versions", help="Comma-separated versions to undelete (default: current_version)")
    sp_und.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    # per-file subs
    sub.add_parser("ls", help="List filenames in the current project")
    sp_cat = sub.add_parser("cat", help="Print a stored file to stdout")
    sp_cat.add_argument("name")
    sp_rm = sub.add_parser("rm", help="Remove one or more stored files")
    sp_rm.add_argument("names", nargs="+")
    sp_mv = sub.add_parser("mv", help="Rename a stored file")
    sp_mv.add_argument("old"); sp_mv.add_argument("new")

    args = p.parse_args()

    addr = args.vault_addr
    token = resolve_token(args.vault_token, force_oidc=getattr(args, "login_oidc", False), addr=addr)
    mount = args.mount_path.strip("/")

    # derive user id from token (no --id)
    owner = args.group or discover_id(addr, token)

    if args.cmd == "push":
        cmd_push(addr, token, mount, owner, args.project, getattr(args, "files"))
    elif args.cmd == "pull":
        cmd_pull(addr, token, mount, owner, args.project, out_dir=getattr(args, "dir"))
    elif args.cmd == "list-projects":
        cmd_list_projects(addr, token, mount, owner)
    elif args.cmd == "delete":
        versions_list = None
        if getattr(args, "versions", None):
            versions_list = [v.strip() for v in args.versions.split(",") if v.strip()]
        cmd_delete(addr, token, mount, owner, args.project,
                   soft=args.soft, destroy=args.destroy, versions=versions_list, force=args.force)
    elif args.cmd == "undelete":
        versions_list = None
        if getattr(args, "versions", None):
            versions_list = [v.strip() for v in args.versions.split(",") if v.strip()]
        cmd_undelete(addr, token, mount, owner, args.project, versions=versions_list, force=args.force)
    elif args.cmd == "ls":
        cmd_ls(addr, token, mount, owner, args.project)
    elif args.cmd == "cat":
        cmd_cat(addr, token, mount, owner, args.project, args.name)
    elif args.cmd == "rm":
        cmd_rm(addr, token, mount, owner, args.project, args.names)
    elif args.cmd == "mv":
        cmd_mv(addr, token, mount, owner, args.project, args.old, args.new)

if __name__ == "__main__":
    main()
   
