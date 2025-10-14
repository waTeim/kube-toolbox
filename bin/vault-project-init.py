#!/usr/bin/env python3
"""
vault_projects_init.py
Initialize a KV v2 mount for per-user, per-project files and install an alias-aware policy
that explicitly allows LIST on both metadata/* and data/* paths.

Defaults:
- Mount:       projects
- Policy name: projects-io
- OIDC path:   auth/oidc

Usage:
  ./vault_projects_init.py --vault-addr https://vault.wat.im --vault-token "$(cat root-token.txt)"
  ./vault_projects_init.py --vault-addr https://vault.wat.im --vault-token ... --oidc-role devs
"""

import argparse, json, os, sys, urllib.request, urllib.error

def vault_request(addr, token, method, path, data=None):
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
        msg = e.read().decode("utf-8", errors="ignore")
        raise SystemExit(f"[ERROR] {method} {url} -> HTTP {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[ERROR] {method} {url} -> {e}")

def ensure_kv_v2(addr, token, mount_path):
    mounts = vault_request(addr, token, "GET", "sys/mounts")
    key = mount_path.strip("/") + "/"
    if key in mounts:
        typ = mounts[key].get("type")
        version = mounts[key].get("options", {}).get("version", "1")
        if typ != "kv" or version != "2":
            raise SystemExit(f"[ERROR] Secrets engine at '{mount_path}/' exists but is not kv v2 (type={typ}, version={version}).")
        print(f"[OK] KV v2 already mounted at {mount_path}/"); return
    payload = {"type": "kv", "options": {"version": "2"}}
    mount_target = f"sys/mounts/{mount_path.strip('/')}"
    vault_request(addr, token, "POST", mount_target, data=payload)
    print(f"[OK] Enabled kv v2 at {mount_path}/")

def discover_oidc_accessor(addr, token, oidc_path):
    data = vault_request(addr, token, "GET", "sys/auth")
    key = oidc_path.strip("/")
    if key.startswith("auth/"):
        key = key.split("/", 1)[1]
    key = key + "/"
    if key not in data:
        available = ", ".join(sorted(k for k in data.keys()))
        raise SystemExit(f"[FATAL] OIDC auth mount '{oidc_path}' not found in sys/auth. Available: {available}")
    accessor = data[key].get("accessor")
    if not accessor:
        raise SystemExit(f"[FATAL] Could not read accessor for auth mount '{oidc_path}'.")
    print(f"[OK] OIDC accessor = {accessor} (from '{oidc_path}')")
    return accessor

def write_policy(addr, token, policy_name, mount_path, oidc_accessor):
    mp = mount_path.strip("/")
    # Explicitly include "list" on both data and metadata paths.
    hcl = f"""
# Per-user, per-project policy for KV v2 under {mp}/
# Alias is derived from OIDC accessor {oidc_accessor}

# Base key (optional single-doc)
path "{mp}/data/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}" {{
  capabilities = ["create","read","update","delete","list"]
}}
path "{mp}/metadata/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}" {{
  capabilities = ["read","list","update","delete"]
}}

# Per-project keys
path "{mp}/data/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}/*" {{
  capabilities = ["create","read","update","delete","list"]
}}
path "{mp}/metadata/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}/*" {{
  capabilities = ["read","list","update","delete"]
}}

# KV v2 versioned ops (base + subpaths)
path "{mp}/delete/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}"     {{ capabilities = ["update"] }}
path "{mp}/undelete/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}"   {{ capabilities = ["update"] }}
path "{mp}/destroy/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}"    {{ capabilities = ["update"] }}
path "{mp}/delete/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}/*"   {{ capabilities = ["update"] }}
path "{mp}/undelete/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}/*" {{ capabilities = ["update"] }}
path "{mp}/destroy/{{{{identity.entity.aliases.{oidc_accessor}.name}}}}/*"  {{ capabilities = ["update"] }}
""".strip()
    vault_request(addr, token, "PUT", f"sys/policies/acl/{policy_name}", data={"policy": hcl})
    print(f"[OK] Wrote/updated policy '{policy_name}' with LIST allowed on data/* and metadata/*")

def maybe_attach_policy_to_oidc_role(addr, token, oidc_path, role, policy_name):
    role_path = f"{oidc_path.strip('/')}/role/{role}"
    data = vault_request(addr, token, "GET", role_path)
    cur = data.get("data", {})
    existing = set(cur.get("token_policies", []))
    if policy_name in existing:
        print(f"[OK] OIDC role '{role}' already includes policy '{policy_name}'")
        return
    updated = sorted(existing | {policy_name})
    vault_request(addr, token, "POST", role_path, data={"token_policies": updated})
    print(f"[OK] Added policy '{policy_name}' to OIDC role '{role}'")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault-addr", default=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"))
    p.add_argument("--vault-token", default=os.getenv("VAULT_TOKEN"))
    p.add_argument("--mount-path", default="projects", help="KV v2 mount path (no trailing slash)")
    p.add_argument("--policy-name", default="projects-io")
    p.add_argument("--oidc-path", default="auth/oidc", help="Auth mount path for OIDC (as shown by 'vault auth list')")
    p.add_argument("--oidc-accessor", default=None, help="Override OIDC accessor (e.g., 'auth_oidc_ABC123')")
    p.add_argument("--oidc-role", default=None, help="Existing OIDC role to update (optional)")
    args = p.parse_args()

    if not args.vault_token:
        raise SystemExit("[FATAL] No token: set VAULT_TOKEN or pass --vault-token.")

    ensure_kv_v2(args.vault_addr, args.vault_token, args.mount_path)
    accessor = args.oidc_accessor or discover_oidc_accessor(args.vault_addr, args.vault_token, args.oidc_path)
    write_policy(args.vault_addr, args.vault_token, args.policy_name, args.mount_path, accessor)
    if args.oidc_role:
        maybe_attach_policy_to_oidc_role(args.vault_addr, args.vault_token, args.oidc_path, args.oidc_role, args.policy_name)

if __name__ == "__main__":
    main()
