#!/usr/bin/env python3
"""
vault_env_init.py
Initialize a KV v2 mount for per-user env vars and install a templated policy.

- Ensures a KV v2 secrets engine exists at --mount-path (default: env)
- Writes/updates an ACL policy (default: env-self) that allows a user to RW only env/<username>
- Optionally adds that policy to an existing OIDC role (token_policies += env-self)

Auth:
  - Uses VAULT_ADDR and VAULT_TOKEN by default; can be overridden via flags.

Examples:
  ./vault_env_init.py
  ./vault_env_init.py --mount-path env --policy-name env-self --oidc-role myapp
"""

import argparse, json, sys, urllib.request, urllib.error

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
    key = mount_path.strip("/") + "/"  # existing mounts are listed with trailing slash
    if key in mounts:
        typ = mounts[key].get("type")
        version = mounts[key].get("options", {}).get("version", "1")
        if typ != "kv" or version != "2":
            raise SystemExit(f"[ERROR] Secrets engine at '{mount_path}/' exists but is not kv v2 (type={typ}, version={version}).")
        print(f"[OK] KV v2 already mounted at {mount_path}/")
        return
    # Enable kv v2 (NO trailing slash here)
    payload = {"type": "kv", "options": {"version": "2"}}
    mount_target = f"sys/mounts/{mount_path.strip('/')}"
    vault_request(addr, token, "POST", mount_target, data=payload)
    print(f"[OK] Enabled kv v2 at {mount_path}/")

def write_policy(addr, token, policy_name, mount_path):
    hcl = f"""
# User may read/write only their own env doc (KV v2)
path "{mount_path}/data/{{{{identity.entity.name}}}}" {{
  capabilities = ["create","read","update","delete"]
}}
path "{mount_path}/metadata/{{{{identity.entity.name}}}}" {{
  capabilities = ["read","list","update","delete"]
}}
path "{mount_path}/delete/{{{{identity.entity.name}}}}"   {{ capabilities = ["update"] }}
path "{mount_path}/undelete/{{{{identity.entity.name}}}}" {{ capabilities = ["update"] }}
path "{mount_path}/destroy/{{{{identity.entity.name}}}}"  {{ capabilities = ["update"] }}
""".strip()
    vault_request(addr, token, "PUT", f"sys/policies/acl/{policy_name}", data={"policy": hcl})
    print(f"[OK] Wrote/updated policy '{policy_name}'")

def maybe_attach_policy_to_oidc_role(addr, token, role, policy_name):
    # Try to read role; if present, append policy to token_policies without clobbering others.
    data = vault_request(addr, token, "GET", f"auth/oidc/role/{role}")
    cur = data.get("data", {})
    existing = set(cur.get("token_policies", []))
    if policy_name in existing:
        print(f"[OK] OIDC role '{role}' already includes policy '{policy_name}'")
        return
    updated = sorted(existing | {policy_name})
    # Attempt partial update; if your Vault requires full fields, this might fail and you'll need to update via CLI.
    vault_request(addr, token, "POST", f"auth/oidc/role/{role}", data={"token_policies": updated})
    print(f"[OK] Added policy '{policy_name}' to OIDC role '{role}'")

def main():
    import os
    p = argparse.ArgumentParser()
    p.add_argument("--vault-addr", default=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"))
    p.add_argument("--vault-token", default=os.getenv("VAULT_TOKEN"))
    p.add_argument("--mount-path", default="env", help="KV v2 mount path (no trailing slash)")
    p.add_argument("--policy-name", default="env-io")
    p.add_argument("--oidc-role", default=None, help="Existing OIDC role to update (optional)")
    args = p.parse_args()

    if not args.vault_token:
        raise SystemExit("[FATAL] No token: set VAULT_TOKEN or pass --vault-token.")

    ensure_kv_v2(args.vault_addr, args.vault_token, args.mount_path)
    write_policy(args.vault_addr, args.vault_token, args.policy_name, args.mount_path)
    if args.oidc_role:
        maybe_attach_policy_to_oidc_role(args.vault_addr, args.vault_token, args.oidc_role, args.policy_name)

if __name__ == "__main__":
    main()
