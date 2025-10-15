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

import sys,argparse, json, urllib.request, urllib.error

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

def ensure_group_alias(addr, token, group_name, group_id, oidc_accessor):
    """
    Ensure an Identity Group alias named `group_name` exists for the given OIDC mount.
    - Reads the group to inspect existing aliases (supports both 'aliases' array and 'alias' object).
    - Creates the alias if missing.
    - Updates the alias name if it exists on the mount but the name differs.
    """
    # Read current group (to see aliases) — tolerate both shapes
    grp = vr(addr, token, "GET", f"identity/group/id/{group_id}").get("data", {}) or {}
    aliases = grp.get("aliases") or []
    if not aliases and isinstance(grp.get("alias"), dict) and grp["alias"]:
        aliases = [grp["alias"]]

    # Find alias for this specific auth mount
    match = next((a for a in aliases if a.get("mount_accessor") == oidc_accessor), None)

    if match is None:
        # No alias for this mount → create one
        payload = {"name": group_name, "mount_accessor": oidc_accessor, "canonical_id": group_id}
        vr(addr, token, "POST", "identity/group-alias", data=payload)
        print(f"[OK] Created Group Alias: {group_name} -> {oidc_accessor}")
        return

    # Alias exists on this mount; ensure the name matches
    alias_id = match.get("id")
    current_name = match.get("name")
    if current_name == group_name:
        print(f"[OK] Group Alias already correct for mount {oidc_accessor}: {current_name}")
        return

    # Update alias name (keeps same canonical_id + mount)
    vr(addr, token, "POST", f"identity/group-alias/id/{alias_id}", data={"name": group_name})
    print(f"[OK] Updated Group Alias name: {current_name} -> {group_name}")

def ensure_identity_group_external(addr, token, group_name, policy_name=None):
    """
    Ensure an Identity Group named `group_name` exists with type='external'.
    If an internal group exists, delete and recreate as external. Optionally attach a policy.
    Returns the group_id.
    """
    gid, gtype = None, None
    try:
        got = vr(addr, token, "GET", f"identity/group/name/{group_name}")
        d = (got.get("data") or {})
        gid, gtype = d.get("id"), d.get("type")
    except SystemExit:
        pass

    if gid and gtype == "external":
        # Optionally ensure policy is attached
        if policy_name:
            cur = vr(addr, token, "GET", f"identity/group/id/{gid}").get("data", {}) or {}
            pols = set(cur.get("policies") or [])
            if policy_name not in pols:
                pols.add(policy_name)
                vr(addr, token, "POST", f"identity/group/id/{gid}", data={"policies": sorted(pols)})
                print(f"[OK] Attached policy '{policy_name}' to Identity Group '{group_name}'")
        print(f"[OK] Identity Group exists (external): {group_name} ({gid})")
        return gid

    if gid and gtype != "external":
        # Recreate as external
        vr(addr, token, "DELETE", f"identity/group/id/{gid}")
        print(f"[INFO] Recreated '{group_name}' as external (was {gtype}).")

    # Create external group
    data = {"name": group_name, "type": "external"}
    if policy_name:
        data["policies"] = [policy_name]
    res = vr(addr, token, "POST", "identity/group", data=data)
    new_gid = (res.get("data") or {}).get("id")
    if not new_gid:
        raise SystemExit("[FATAL] Could not create external Identity Group.")
    print(f"[OK] Created external Identity Group: {group_name} ({new_gid})")
    return new_gid


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
    policy_name = upsert_group_policy(addr, token, group, mount=args.mount_path)
    group_id = ensure_identity_group_external(addr, token, group, policy_name=policy_name)
    ensure_group_alias(addr, token, group, group_id, accessor)
    attach_policy(addr, token, group_id, policy_name)
    maybe_set_groups_claim(addr, token, args.oidc_path, args.role, args.groups_claim)
    print("[DONE] Group namespace ready. Users re-login; Vault will map token groups to this group.")

if __name__ == "__main__":
    main()
