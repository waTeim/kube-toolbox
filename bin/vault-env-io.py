#!/usr/bin/env python3
"""
vault_env_push_pull.py
Push/pull a single JSON file to/from KV v2 at <mount>/data/<id>.

Token resolution order:
1) --vault-token flag
2) AUTH environment variable
3) VAULT_TOKEN environment variable
4) ~/.vault-token file (if present)
5) If none of the above, automatically run: `vault login -method=oidc -format=json`
   and use the returned client token.

Assumptions:
- JSON file is the "Option B" KV v2 shape: {"data": { "KEY": "VALUE", ... }}
- By default, the per-user doc lives at: <mount>/<id>, where <id> is the OIDC username.
- The script will try to auto-detect <id> from the Vault token's metadata (OIDC).
  If it cannot, you must pass --id.

Auth:
  - Uses VAULT_ADDR by default; can be overridden via --vault-addr.

Examples:
  # Push (write/replace)
  ./vault_env_push_pull.py push --file env.json
  ./vault_env_push_pull.py push --file env.json --id jeff --mount-path env

  # Pull (read) into a file
  ./vault_env_push_pull.py pull --out env.json
  ./vault_env_push_pull.py pull --out env.json --id jeff
"""

import argparse, json, os, sys, urllib.request, urllib.error, subprocess

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
    # Use /auth/token/lookup-self to fetch meta.username (commonly set by OIDC user_claim).
    info = vault_request(addr, token, "GET", "auth/token/lookup-self")
    data = info.get("data", {})
    meta = data.get("meta", {}) or {}
    username = meta.get("username") or meta.get("user") or None
    if username:
        return username
    # Some tokens have display_name like "oidc-<user>"; try to peel it.
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
        # Non-fatal; just fall through to other methods.
        print(f"[WARN] Could not read token file {path}: {e}", file=sys.stderr)
        return None

def run_vault_login_oidc():
    """
    Run `vault login -method=oidc -format=json` and return the client token.
    Relies on the local vault CLI being available in PATH and VAULT_ADDR set.
    Falls back to device flow automatically if a browser can't be launched.
    """
    try:
        proc = subprocess.run(
            ["vault", "login", "-method=oidc", "-format=json"],
            check=False, capture_output=True, text=True
        )
    except FileNotFoundError:
        raise SystemExit("[FATAL] vault CLI not found in PATH, and no token provided. Install HashiCorp Vault CLI or pass --vault-token.")

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        msg = stderr or stdout or "unknown error"
        raise SystemExit(f"[FATAL] `vault login -method=oidc` failed: {msg}")

    try:
        obj = json.loads(proc.stdout)
        token = obj.get("auth", {}).get("client_token")
        if not token:
            raise ValueError("login output missing auth.client_token")
        return token
    except Exception as e:
        raise SystemExit(f"[FATAL] Could not parse login JSON: {e}\nOutput was:\n{proc.stdout}")

def resolve_token(cli_token: str | None):
    """
    Implement the requested precedence:
      1) --vault-token
      2) AUTH env var
      3) VAULT_TOKEN env var
      4) ~/.vault-token file
      5) Trigger `vault login -method=oidc -format=json`
    """
    if cli_token:
        return cli_token

    env_auth = os.getenv("AUTH")
    if env_auth:
        return env_auth

    env_vault = os.getenv("VAULT_TOKEN")
    if env_vault:
        return env_vault

    home_token = read_token_from_file(os.path.expanduser("~/.vault-token"))
    if home_token:
        return home_token

    # Nothing found -> do interactive OIDC login via vault CLI
    print("[INFO] No token via flag/ENV/file; invoking `vault login -method=oidc`...", file=sys.stderr)
    return run_vault_login_oidc()

def cmd_push(addr, token, mount, user_id, file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise SystemExit(f"[FATAL] Failed to read JSON from {file_path}: {e}")
    # Enforce Option B: {"data": {...}}
    if not isinstance(payload, dict) or "data" not in payload or not isinstance(payload["data"], dict):
        raise SystemExit("[FATAL] JSON must be the KV v2 shape: {'data': { ... }}")
    resp = vault_request(addr, token, "POST", f"{mount}/data/{user_id}", data=payload)
    version = resp.get("data", {}).get("version")
    print(f"[OK] Wrote env at {mount}/{user_id} (version={version})")

def cmd_pull(addr, token, mount, user_id, out_path, create_if_missing=False):
    resp = vault_request(addr, token, "GET", f"{mount}/data/{user_id}", allow_404=create_if_missing)
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
    print(f"[OK] Wrote {out_path} from {mount}/{user_id}")



def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p.add_argument("--vault-addr", default=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"))
    p.add_argument("--vault-token", default=None, help="Explicit Vault token (overrides all other sources)")
    p.add_argument("--mount-path", default="env", help="KV v2 mount path (no trailing slash)")
    p.add_argument("--id", default=None, help="User/record id (defaults to OIDC username from token)")

    sp_push = sub.add_parser("push", help="Push JSON to KV v2")
    sp_push.add_argument("--file", required=True, help="Path to JSON file in the shape {'data': {...}}")

    sp_pull = sub.add_parser("pull", help="Pull JSON from KV v2")
    sp_pull.add_argument("--out", required=True, help="Path to write JSON")
    sp_pull.add_argument("--create-if-missing", action="store_true",help="If secret does not exist, write an empty skeleton instead of failing")

    args = p.parse_args()

    # Resolve a token per requested precedence (flag -> AUTH -> VAULT_TOKEN -> file -> login)
    token = resolve_token(args.vault_token)
    if not token:
        raise SystemExit("[FATAL] Could not obtain a Vault token.")

    # Now we can use VAULT_ADDR passed/ENV
    addr = args.vault_addr
    mount_data_prefix = args.mount_path.strip("/")

    user_id = args.id or discover_id(addr, token)
    if not user_id:
        raise SystemExit("[FATAL] Could not determine --id from token; pass --id explicitly (e.g., --id jeff).")

    if args.cmd == "push":
        cmd_push(addr, token, mount_data_prefix, user_id, getattr(args, "file"))
    elif args.cmd == "pull":
        cmd_pull(addr, token, mount_data_prefix, user_id, getattr(args, "out"),
                create_if_missing=getattr(args, "create_if_missing"))

if __name__ == "__main__":
    main()
