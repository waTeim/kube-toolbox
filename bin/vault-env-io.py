#!/usr/bin/env python3
"""
vault_env_push_pull.py
Push/pull a single JSON file to/from KV v2 at <mount>/data/<user>/<project>.

New:
- --project (default: "default")
- list-projects subcommand (LIST on <mount>/metadata/<user>)
"""

import argparse, json, os, sys, urllib.request, urllib.error, subprocess
from urllib.parse import quote

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
    return None

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

def run_vault_login_oidc():
    try:
        proc = subprocess.run(
            ["vault", "login", "-method=oidc", "-format=json"],
            check=False, capture_output=True, text=True
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

def resolve_token(cli_token: str | None):
    if cli_token:
        return cli_token
    for envvar in ("AUTH", "VAULT_TOKEN"):
        t = os.getenv(envvar)
        if t:
            return t
    t = read_token_from_file(os.path.expanduser("~/.vault-token"))
    if t:
        return t
    print("[INFO] No token via flag/ENV/file; invoking `vault login -method=oidc`...", file=sys.stderr)
    return run_vault_login_oidc()

def kv_path(mount: str, user_id: str, project: str, *, kind: str):
    """kind: 'data' or 'metadata'"""
    mp = mount.strip("/")
    safe_user = quote(user_id, safe="")
    safe_proj = quote(project, safe="")
    if kind not in ("data", "metadata"):
        raise ValueError("kind must be data|metadata")
    return f"{mp}/{kind}/{safe_user}/{safe_proj}" if safe_proj else f"{mp}/{kind}/{safe_user}"

def cmd_push(addr, token, mount, user_id, project, file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise SystemExit(f"[FATAL] Failed to read JSON from {file_path}: {e}")
    if not isinstance(payload, dict) or "data" not in payload or not isinstance(payload["data"], dict):
        raise SystemExit("[FATAL] JSON must be the KV v2 shape: {'data': { ... }}")
    path = kv_path(mount, user_id, project, kind="data")
    resp = vault_request(addr, token, "POST", path, data=payload)
    ver = resp.get("data", {}).get("version")
    print(f"[OK] Wrote env at {mount.strip('/')}/{user_id}/{project or ''} (version={ver})")

def cmd_pull(addr, token, mount, user_id, project, out_path, create_if_missing=False):
    path = kv_path(mount, user_id, project, kind="data")
    resp = vault_request(addr, token, "GET", path, allow_404=create_if_missing)
    if resp.get("_missing"):
        out = {"data": {}}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, sort_keys=True); f.write("\n")
        print(f"[OK] Secret missing; wrote empty skeleton to {out_path}")
        return
    doc = resp.get("data", {}).get("data", {})
    out = {"data": doc}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True); f.write("\n")
    print(f"[OK] Wrote {out_path} from {mount.strip('/')}/{user_id}/{project or ''}")

def cmd_list_projects(addr, token, mount, user_id):
    # LIST on metadata/<user_id> to enumerate child keys (projects)
    mp = mount.strip("/")
    safe_user = quote(user_id, safe="")
    resp = vault_request(addr, token, "LIST", f"{mp}/metadata/{safe_user}", allow_404=True)
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


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p.add_argument("--vault-addr", default=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"))
    p.add_argument("--vault-token", default=None, help="Explicit Vault token (overrides all other sources)")
    p.add_argument("--mount-path", default="env", help="KV v2 mount path (no trailing slash)")
    p.add_argument("--id", default=None, help="User/record id (defaults to OIDC username from token)")
    p.add_argument("--project", default="default", help="Project key under your namespace")

    sp_push = sub.add_parser("push", help="Push JSON to KV v2")
    sp_push.add_argument("--file", required=True, help="Path to JSON file in the shape {'data': {...}}")

    sp_pull = sub.add_parser("pull", help="Pull JSON from KV v2")
    sp_pull.add_argument("--out", required=True, help="Path to write JSON (same shape {'data': {...}})")
    sp_pull.add_argument("--create-if-missing", action="store_true",
                         help="If secret does not exist, write an empty skeleton instead of failing")

    sub.add_parser("list-projects", help="List project names under your namespace")

    args = p.parse_args()
    token = resolve_token(args.vault_token)
    addr = args.vault_addr
    mount = args.mount_path.strip("/")
    user_id = args.id or discover_id(addr, token)
    if not user_id:
        raise SystemExit("[FATAL] Could not determine --id from token; pass --id explicitly (e.g., --id jeff).")

    if args.cmd == "push":
        cmd_push(addr, token, mount, user_id, args.project, getattr(args, "file"))
    elif args.cmd == "pull":
        cmd_pull(addr, token, mount, user_id, args.project, getattr(args, "out"),
                 create_if_missing=getattr(args, "create_if_missing"))
    elif args.cmd == "list-projects":
        cmd_list_projects(addr, token, mount, user_id)

if __name__ == "__main__":
    main()
