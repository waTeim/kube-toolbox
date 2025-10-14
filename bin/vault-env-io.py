#!/usr/bin/env python3
"""
vault_env_push_pull.py
──────────────────────
Store/retrieve ANY file in KV v2 at <mount>/data/<user>/<project>, with metadata.

Commands:
  push <FILE>           Store a file as base64 blob + metadata (key 'blob')
  pull [--dir DIR]      Restore the stored file to its original filename
  list-projects         List child keys (projects) under your alias
  delete [mode]         Delete a project (purge/soft/destroy)
  undelete [--versions] Undelete soft-deleted versions (default: current_version)

Auth resolution order:
  1) --vault-token
  2) $AUTH / $VAULT_TOKEN
  3) ~/.vault-token
  4) `vault login -method=oidc`  (forced if --login-oidc)

Notes:
- All HTTP calls include X-Vault-Namespace if --namespace is set.
- OIDC CLI login is executed with VAULT_ADDR/VAULT_NAMESPACE set from flags.
"""

import argparse, base64, hashlib, json, mimetypes, os, sys, subprocess, urllib.error, urllib.request
from urllib.parse import quote

# ------------------------------- HTTP / Vault helpers -------------------------------

def vault_request(addr, token, method, path, data=None, *, allow_404=False, namespace=None):
    url = addr.rstrip("/") + "/v1/" + path.lstrip("/")
    req = urllib.request.Request(url, method=method)
    req.add_header("X-Vault-Token", token)
    if namespace:
        req.add_header("X-Vault-Namespace", namespace)
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

def run_vault_login_oidc(addr, namespace=None):
    env = os.environ.copy()
    env["VAULT_ADDR"] = addr
    if namespace:
        env["VAULT_NAMESPACE"] = namespace
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

def resolve_token(cli_token: str | None, *, force_oidc: bool, addr: str, namespace: str | None):
    # 1) explicit flag wins
    if cli_token:
        return cli_token
    # 2) optionally force OIDC login
    if force_oidc:
        print("[INFO] Forcing OIDC login via `vault login -method=oidc`...", file=sys.stderr)
        return run_vault_login_oidc(addr, namespace)
    # 3) env vars
    for envvar in ("AUTH", "VAULT_TOKEN"):
        t = os.getenv(envvar)
        if t:
            return t
    # 4) ~/.vault-token
    t = read_token_from_file(os.path.expanduser("~/.vault-token"))
    if t:
        return t
    # 5) fallback to OIDC
    print("[INFO] No token via flag/ENV/file; invoking `vault login -method=oidc`...", file=sys.stderr)
    return run_vault_login_oidc(addr, namespace)

def discover_id(addr, token, namespace=None):
    info = vault_request(addr, token, "GET", "auth/token/lookup-self", namespace=namespace)
    data = info.get("data", {})
    meta = data.get("meta", {}) or {}
    username = meta.get("username") or meta.get("user")
    if username:
        return username
    dn = data.get("display_name") or ""
    if dn.startswith("oidc-") and len(dn) > 5:
        return dn[5:]
    return None

def kv_path(mount: str, user_id: str, project: str, *, kind: str):
    """
    kind ∈ { data, metadata, delete, undelete, destroy }
    """
    mp = mount.strip("/")
    safe_user = quote(user_id, safe="")
    safe_proj = quote(project, safe="")
    if kind not in ("data", "metadata", "delete", "undelete", "destroy"):
        raise ValueError("kind must be data|metadata|delete|undelete|destroy")
    return f"{mp}/{kind}/{safe_user}/{safe_proj}" if safe_proj else f"{mp}/{kind}/{safe_user}"

# ------------------------------- Blob helpers -------------------------------

def _file_to_record(path_fs: str):
    with open(path_fs, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    sha = hashlib.sha256(raw).hexdigest()
    name = os.path.basename(path_fs)
    mime, _ = mimetypes.guess_type(name)
    return {
        "filename": name,
        "encoding": "base64",
        "size_bytes": len(raw),
        "sha256": sha,
        "mime": mime or "application/octet-stream",
        "bytes": b64,
    }

def _record_to_file(rec: dict, out_dir: str | None = None):
    if not isinstance(rec, dict) or rec.get("encoding") != "base64" or "bytes" not in rec:
        raise SystemExit("[FATAL] Secret content is not a blob record with base64 'bytes'.")
    data = base64.b64decode(rec["bytes"])
    if "sha256" in rec:
        sha = hashlib.sha256(data).hexdigest()
        if sha != rec["sha256"]:
            raise SystemExit(f"[FATAL] SHA256 mismatch: expected {rec['sha256']}, got {sha}")
    fname = rec.get("filename") or "blob.bin"
    tgt_dir = os.path.abspath(out_dir or ".")
    os.makedirs(tgt_dir, exist_ok=True)
    out_path = os.path.join(tgt_dir, fname)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path, len(data)

# ------------------------------- Commands -------------------------------

def cmd_push(addr, token, mount, user_id, project, file_path, namespace=None, warn_threshold=900_000):
    if not os.path.isfile(file_path):
        raise SystemExit(f"[FATAL] Not a file: {file_path}")
    rec = _file_to_record(file_path)
    if rec["size_bytes"] > warn_threshold:
        print(f"[WARN] File is {rec['size_bytes']} bytes. KV v2 is for small secrets; consider object storage for larger blobs.", file=sys.stderr)
    payload = {"data": {"blob": rec}}
    path = kv_path(mount, user_id, project, kind="data")
    resp = vault_request(addr, token, "POST", path, data=payload, namespace=namespace)
    ver = resp.get("data", {}).get("version")
    print(f"[OK] Stored '{rec['filename']}' ({rec['size_bytes']} bytes, sha256={rec['sha256'][:12]}…) at {mount.strip('/')}/{user_id}/{project or ''} (version={ver})")

def cmd_pull(addr, token, mount, user_id, project, out_dir, namespace=None):
    path = kv_path(mount, user_id, project, kind="data")
    resp = vault_request(addr, token, "GET", path, allow_404=True, namespace=namespace)
    if resp.get("_missing"):
        print("[INFO] Nothing stored for this project yet.")
        return
    doc = resp.get("data", {}).get("data", {})
    blob = doc.get("blob")
    if not blob:
        print("[INFO] No file blob found at this path.")
        return
    out_path, size = _record_to_file(blob, out_dir)
    print(f"[OK] Wrote {size} bytes to {out_path}")

def cmd_list_projects(addr, token, mount, user_id, namespace=None):
    mp = mount.strip("/")
    safe_user = quote(user_id, safe="")
    resp = vault_request(addr, token, "LIST", f"{mp}/metadata/{safe_user}", allow_404=True, namespace=namespace)
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

def _get_current_version(addr, token, mount, user_id, project, namespace=None):
    meta_path = kv_path(mount, user_id, project, kind="metadata")
    resp = vault_request(addr, token, "GET", meta_path, allow_404=True, namespace=namespace)
    if resp.get("_missing"):
        return None, {}
    d = resp.get("data", {}) or {}
    return d.get("current_version"), d

def cmd_delete(addr, token, mount, user_id, project, *, soft=False, destroy=False, versions=None, force=False, namespace=None):
    if soft and destroy:
        raise SystemExit("[FATAL] Choose either --soft or --destroy, not both.")

    # Determine versions if needed
    if soft or destroy:
        cur, _ = _get_current_version(addr, token, mount, user_id, project, namespace=namespace)
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
    target = f"{mount.strip('/')}/{user_id}/{project or ''}"
    if not force:
        ans = input(f"About to {action} at {target}. Proceed? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("[INFO] Aborted.")
            return

    if soft:
        path = kv_path(mount, user_id, project, kind="delete")
        vault_request(addr, token, "POST", path, data={"versions": versions}, namespace=namespace)
        print(f"[OK] Soft-deleted versions {versions} at {target}.")
    elif destroy:
        path = kv_path(mount, user_id, project, kind="destroy")
        vault_request(addr, token, "POST", path, data={"versions": versions}, namespace=namespace)
        print(f"[OK] Permanently destroyed versions {versions} at {target}.")
    else:
        meta_path = kv_path(mount, user_id, project, kind="metadata")
        vault_request(addr, token, "DELETE", meta_path, data=None, namespace=namespace)
        print(f"[OK] Purged project '{project}' (all versions + metadata removed) at {target}.")

def cmd_undelete(addr, token, mount, user_id, project, versions=None, force=False, namespace=None):
    cur, _ = _get_current_version(addr, token, mount, user_id, project, namespace=namespace)
    if versions is None or versions == []:
        if not cur:
            print("[INFO] No versions found to undelete.")
            return
        versions = [cur]
    try:
        versions = [int(v) for v in versions]
    except Exception:
        raise SystemExit("[FATAL] versions must be integers.")
    target = f"{mount.strip('/')}/{user_id}/{project or ''}"
    if not force:
        ans = input(f"About to UNDELETE versions {versions} at {target}. Proceed? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("[INFO] Aborted.")
            return
    path = kv_path(mount, user_id, project, kind="undelete")
    vault_request(addr, token, "POST", path, data={"versions": versions}, namespace=namespace)
    print(f"[OK] Undeleted versions {versions} at {target}.")

# ------------------------------- CLI -------------------------------

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    # global args
    p.add_argument("--vault-addr", default=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"))
    p.add_argument("--namespace", default=os.getenv("VAULT_NAMESPACE"), help="Vault namespace (Enterprise)")
    p.add_argument("--vault-token", default=None, help="Explicit Vault token (overrides all other sources)")
    p.add_argument("--login-oidc", action="store_true", help="Force OIDC login via `vault login -method=oidc`")
    p.add_argument("--mount-path", default="env", help="KV v2 mount path (no trailing slash)")
    p.add_argument("--id", default=None, help="User/record id (defaults to OIDC username from token)")
    p.add_argument("--project", default="default", help="Project key under your namespace")

    # subcommands
    sp_push = sub.add_parser("push", help="Push a file to KV v2 (stored as base64 blob + metadata)")
    sp_push.add_argument("file", help="Path to the file to store")

    sp_pull = sub.add_parser("pull", help="Pull the stored file, writing to its original filename")
    sp_pull.add_argument("--dir", default=".", help="Directory to write the file into (default: current dir)")

    sub.add_parser("list-projects", help="List project names under your namespace")

    sp_del = sub.add_parser("delete", help="Delete a project (purge by default)")
    g = sp_del.add_mutually_exclusive_group()
    g.add_argument("--soft", action="store_true", help="Soft-delete versions (default: current version)")
    g.add_argument("--destroy", action="store_true", help="Permanently destroy specific versions (requires --versions)")
    sp_del.add_argument("--versions", help="Comma-separated versions for --soft/--destroy (default for --soft: current version)")
    sp_del.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    sp_und = sub.add_parser("undelete", help="Undelete soft-deleted versions (default: current_version)")
    sp_und.add_argument("--versions", help="Comma-separated versions to undelete (default: current_version)")
    sp_und.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    args = p.parse_args()

    addr = args.vault_addr
    namespace = args.namespace or None
    token = resolve_token(args.vault_token, force_oidc=getattr(args, "login_oidc", False), addr=addr, namespace=namespace)
    mount = args.mount_path.strip("/")

    # best-effort whoami; if it fails, require --id
    try:
        user_id = args.id or discover_id(addr, token, namespace=namespace)
    except SystemExit:
        user_id = args.id
    if not user_id:
        raise SystemExit("[FATAL] Could not determine --id from token; pass --id explicitly (e.g., --id jeff).")

    if args.cmd == "push":
        cmd_push(addr, token, mount, user_id, args.project, getattr(args, "file"), namespace=namespace)
    elif args.cmd == "pull":
        cmd_pull(addr, token, mount, user_id, args.project, out_dir=getattr(args, "dir"), namespace=namespace)
    elif args.cmd == "list-projects":
        cmd_list_projects(addr, token, mount, user_id, namespace=namespace)
    elif args.cmd == "delete":
        versions_list = None
        if args.versions:
            versions_list = [v.strip() for v in args.versions.split(",") if v.strip()]
        cmd_delete(addr, token, mount, user_id, args.project,
                   soft=args.soft, destroy=args.destroy, versions=versions_list, force=args.force, namespace=namespace)
    elif args.cmd == "undelete":
        versions_list = None
        if args.versions:
            versions_list = [v.strip() for v in args.versions.split(",") if v.strip()]
        cmd_undelete(addr, token, mount, user_id, args.project, versions=versions_list, force=args.force, namespace=namespace)

if __name__ == "__main__":
    main()
