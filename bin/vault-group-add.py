#!/usr/bin/env python3
"""
vault-group-add.py
Provision a shared *group* namespace for projects KV v2 using Vault Identity Groups.

What it does (idempotent):
  1) Upsert policy:  projects-io-<GROUP>  (scopes to projects/<GROUP>/*)
  2) Ensure Identity Group named <GROUP>
  3) Ensure Group Alias <GROUP> bound to your OIDC mount
  4) Attach the policy to the Identity Group
  5) (Optional) Set groups_claim on an OIDC role (default: devs)

Usage:
  ./vault-group-add.py GROUP --vault-addr https://vault.wat.im --vault-token $(cat root-token.txt) [--role devs] [--groups-claim https://wat.im/groups]
"""

import argparse, json, urllib.request, urllib.error

def vr(addr, token, method, path, data=None):
    url = addr.rstrip("/") + "/v1/" + path.lstrip("/")
    req = urllib.request.Request(url, method=method)
    req.add_header("X-Vault-Token", token)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
        req.data = body
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        raise SystemExit(f"[ERROR] {method} {url} -> HTTP {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[ERROR] {method} {url} -> {e}")

def get_oidc_accessor(addr, token, oidc_path):
    data = vr(addr, token, "GET", "sys/auth")
    key = oidc_path.strip("/")
    if key.startswith("auth/"): key = key.split("/", 1)[1]
    key = key + "/"
    if key not in data: raise SystemExit(f"[FATAL] OIDC mount '{oidc_path}' not found.")
    acc = data[key].get("accessor")
    if not acc: raise SystemExit(f"[FATAL] Missing accessor on '{oidc_path}'.")
    print(f"[OK] OIDC accessor = {acc} (from '{oidc_path}')")
    return acc

def upsert_group_policy(addr, token, group, mount="projects"):
    mp = mount.strip("/")
    hcl = f"""
path "{mp}/data/{group}"         {{ capabilities = ["create","read","update","delete","list"] }}
path "{mp}/data/{group}/*"       {{ capabilities = ["create","read","update","delete","list"] }}
path "{mp}/metadata/{group}"     {{ capabilities = ["read","list","update","delete"] }}
path "{mp}/metadata/{group}/*"   {{ capabilities = ["read","list","update","delete"] }}
path "{mp}/delete/{group}"       {{ capabilities = ["update"] }}
path "{mp}/delete/{group}/*"     {{ capabilities = ["update"] }}
path "{mp}/undelete/{group}"     {{ capabilities = ["update"] }}
path "{mp}/undelete/{group}/*"   {{ capabilities = ["update"] }}
path "{mp}/destroy/{group}"      {{ capabilities = ["update"] }}
path "{mp}/destroy/{group}/*"    {{ capabilities = ["update"] }}
""".strip()
    name = f"projects-io-{group}"
    vr(addr, token, "PUT", f"sys/policies/acl/{name}", data={"policy": hcl})
    print(f"[OK] Upserted policy '{name}'")
    return name

def ensure_identity_group(addr, token, group):
    # Try by-name (Vault >= 1.20)
    try:
        got = vr(addr, token, "GET", f"identity/group/name/{group}")
        gid = (got.get("data") or {}).get("id")
        if gid:
            print(f"[OK] Identity Group exists: {group} ({gid})")
            return gid
    except SystemExit:
        pass
    res = vr(addr, token, "POST", "identity/group", data={"name": group})
    gid = (res.get("data") or {}).get("id")
    if not gid: raise SystemExit("[FATAL] Could not create Identity Group.")
    print(f"[OK] Created Identity Group: {group} ({gid})")
    return gid

def ensure_group_alias(addr, token, group, group_id, oidc_accessor):
    payload = {"name": group, "mount_accessor": oidc_accessor, "canonical_id": group_id}
    try:
        vr(addr, token, "POST", "identity/group-alias", data=payload)
        print(f"[OK] Created Group Alias: {group} -> {oidc_accessor}")
    except SystemExit:
        print(f"[INFO] Group Alias may already exist for '{group}' (continuing).")

def attach_policy(addr, token, group_id, policy_name):
    cur = vr(addr, token, "GET", f"identity/group/id/{group_id}").get("data", {})
    pols = set(cur.get("policies") or [])
    if policy_name in pols:
        print(f"[OK] Policy already attached.")
        return
    pols.add(policy_name)
    vr(addr, token, "POST", f"identity/group/id/{group_id}", data={"policies": sorted(pols)})
    print(f"[OK] Attached policy '{policy_name}' to Identity Group.")

def maybe_set_groups_claim(addr, token, oidc_path, role, claim):
    if not claim:
        return
    vr(addr, token, "POST", f"{oidc_path.strip('/')}/role/{role}", data={"groups_claim": claim})
    print(f"[OK] Set groups_claim on role '{role}' to: {claim}")

def main():
    ap = argparse.ArgumentParser(description="Provision a group namespace (policy + identity group + alias).")
    ap.add_argument("GROUP", help="group slug (shared namespace), e.g. platform, team-alpha")
    ap.add_argument("--vault-addr", required=True)
    ap.add_argument("--vault-token", required=True, help="admin/root token")
    ap.add_argument("--oidc-path", default="auth/oidc", help="OIDC/JWT auth mount path")
    ap.add_argument("--mount-path", default="projects", help="KV v2 mount path")
    ap.add_argument("--role", default="devs", help="OIDC role to (optionally) set groups_claim on")
    ap.add_argument("--groups-claim", default=None,
                    help="JWT claim key carrying groups (e.g., https://wat.im/groups). If set, updates the role's groups_claim.")
    args = ap.parse_args()

    addr, token, group = args.vault_addr, args.vault_token, args.GROUP
    accessor = get_oidc_accessor(addr, token, args.oidc_path)
    pol = upsert_group_policy(addr, token, group, mount=args.mount_path)
    gid = ensure_identity_group(addr, token, group)
    ensure_group_alias(addr, token, group, gid, accessor)
    attach_policy(addr, token, gid, pol)
    maybe_set_groups_claim(addr, token, args.oidc_path, args.role, args.groups_claim)
    print("[DONE] Group namespace ready. Users re-login; Vault will map token groups to this group.")

if __name__ == "__main__":
    main()
