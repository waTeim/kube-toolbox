#!/usr/bin/env python3
# Minimal Vault JWT/OIDC setup (short flags, provider-agnostic)
# Enables/keeps a jwt auth mount at --mount (default: oidc), writes OIDC config,
# and creates/updates one role with UI + CLI callbacks.
# Example:
#   python setup_vault_oidc_min.py --vault-addr https://vault.example.com --vault-token-file ~/.vault-token --issuer https://your-idp.example.com --client-id XXX --client-secret YYY

import argparse, getpass, os, sys
from typing import Optional
from urllib.parse import urlparse
import requests

def normalize_base(u: str) -> str:
    u = u.strip().rstrip("/")
    if not u:
        return u
    parsed = urlparse(u)
    if not parsed.scheme:
        u = "https://" + u
    elif parsed.scheme == "http":
        raise SystemExit("Issuer must be HTTPS. Use https://…")
    return u

def adopt_issuer_from_discovery(issuer_hint: str) -> str:
    u = issuer_hint.strip()
    if not urlparse(u).scheme:
        u = "https://" + u
    url = u.rstrip("/") + "/.well-known/openid-configuration"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    disc = r.json().get("issuer", "")
    if not disc:
        raise SystemExit(f"No 'issuer' in discovery at {url}")
    # Use EXACT string the IdP reports (includes trailing slash if present)
    return disc

class Vault:
    def __init__(self, addr: str, token: str, namespace: Optional[str] = None, verify: bool | str = True):
        self.addr = addr.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-Vault-Token": token})
        if namespace:
            self.session.headers.update({"X-Vault-Namespace": namespace})
        self.verify = verify
    def _u(self, p: str) -> str:
        return self.addr + ("/v1/" + p.lstrip("/") if not p.startswith("/v1/") else p)
    def get(self, p: str):  return self.session.get(self._u(p), verify=self.verify)
    def post(self, p: str, body: dict): return self.session.post(self._u(p), json=body, verify=self.verify)

def prompt_missing(a):
    def ask(msg, secret=False): return getpass.getpass(msg + ": ") if secret else input(msg + ": ").strip()
    if not a.vault_addr: a.vault_addr = ask("Vault address (e.g., https://vault.example.com)")
    if not a.vault_token and not a.vault_token_file:
        if (ask("Provide Vault token directly? [y/N]") or "n").lower().startswith("y"): a.vault_token = getpass.getpass("Vault token: ")
        else: a.vault_token_file = ask("Path to Vault token file (e.g., ~/.vault-token)")
    if a.vault_token_file and not a.vault_token:
        try:
            with open(os.path.expanduser(a.vault_token_file), "r") as f: a.vault_token = f.read().strip()
        except OSError as e:
            print(f"Failed to read token file: {e}", file=sys.stderr); sys.exit(1)
    if not a.issuer: a.issuer = ask("OIDC issuer base URL (e.g., https://your-idp.example.com)")
    if not a.client_id: a.client_id = ask("OIDC client ID")
    if not a.client_secret: a.client_secret = ask("OIDC client secret", secret=True)

def ensure_mount(v: Vault, mount: str):
    r = v.get("sys/auth"); r.raise_for_status()
    mounts = r.json(); key = mount.rstrip("/") + "/"
    if key in mounts:
        t = mounts[key]["type"]; print(f"[auth] mount '{mount}' exists (type={t}).")
        if t != "jwt": raise SystemExit(f"Auth mount '{mount}' is type '{t}', expected 'jwt'. Choose another --mount or remove it.")
        return
    print(f"[auth] enabling jwt at '{mount}' ...")
    r = v.post(f"sys/auth/{mount}", {"type": "jwt"})
    if r.status_code not in (200, 204): raise SystemExit(f"Enable auth failed [{r.status_code}]: {r.text}")
    print("[auth] enabled.")

def write_oidc_config(v: Vault, mount: str, issuer: str, client_id: str, client_secret: str, default_role: str, ca_pem: Optional[str]):
    body = {"oidc_discovery_url": issuer, "oidc_client_id": client_id, "oidc_client_secret": client_secret, "default_role": default_role}
    if ca_pem: body["oidc_discovery_ca_pem"] = ca_pem
    print(f"[config] writing auth/{mount}/config ...")
    r = v.post(f"auth/{mount}/config", body)
    if r.status_code not in (200, 204): raise SystemExit(f"Write OIDC config failed [{r.status_code}]: {r.text}")
    print("[config] ok.")

def upsert_role(v: Vault, mount: str, role: str, vault_addr: str, policies: list[str], groups_claim: Optional[str], scopes_csv: str, ttl: str):
    ui_cb = f"{vault_addr.rstrip('/')}/ui/vault/auth/{mount}/oidc/callback"
    scopes = [s.strip() for s in scopes_csv.split(",") if s.strip()] or ["openid","profile","email"]
    body = {"role_type": "oidc", "user_claim": "email", "oidc_scopes": scopes, "allowed_redirect_uris": [ui_cb, "http://localhost:8250/oidc/callback"], "token_policies": policies, "token_ttl": ttl}
    if groups_claim: body["groups_claim"] = groups_claim
    print(f"[role] upserting auth/{mount}/role/{role} ...")
    r = v.post(f"auth/{mount}/role/{role}", body)
    if r.status_code not in (200, 204): raise SystemExit(f"Write role failed [{r.status_code}]: {r.text}")
    print("[role] ok.")

def main():
    ap = argparse.ArgumentParser(description="Minimal Vault OIDC setup (auth method + role) with short flags.")
    ap.add_argument("--vault-addr", help="Vault address (also used for UI callback), e.g. https://vault.example.com")
    ap.add_argument("--vault-token", help="Vault admin token (or use --vault-token-file)")
    ap.add_argument("--vault-token-file", help="File containing Vault token (e.g., ~/.vault-token)")
    ap.add_argument("--vault-namespace", help="(Optional) Vault namespace header")
    ap.add_argument("--insecure-skip-verify", action="store_true", help="Skip TLS verify (NOT recommended)")
    ap.add_argument("--mount", default="oidc", help="Auth mount path (default: oidc)")
    ap.add_argument("--role", default="devs", help="Role name (default: devs)")
    ap.add_argument("--policies", default="default", help="Comma-separated token policies (default: default)")
    ap.add_argument("--issuer", help="OIDC issuer base URL (e.g., https://your-idp.example.com). Use BASE, not /.well-known/…")
    ap.add_argument("--client-id", help="OIDC client ID")
    ap.add_argument("--client-secret", help="OIDC client secret")
    ap.add_argument("--scopes", default="openid,profile,email", help="Comma-separated scopes (default: openid,profile,email)")
    ap.add_argument("--groups-claim", help="(Optional) Custom groups claim URI in ID token")
    ap.add_argument("--ca-pem-file", help="(Optional) Path to PEM bundle if your issuer uses a custom CA")
    ap.add_argument("--token-ttl", default="24h", help="Issued Vault token TTL (default: 24h)")
    args = ap.parse_args()

    # prompts for anything missing
    def ask(m, secret=False): return getpass.getpass(m + ": ") if secret else input(m + ": ").strip()
    if not args.vault_addr: args.vault_addr = ask("Vault address (e.g., https://vault.example.com)")
    if not args.vault_token and not args.vault_token_file:
        if (ask("Provide Vault token directly? [y/N]") or "n").lower().startswith("y"): args.vault_token = getpass.getpass("Vault token: ")
        else: args.vault_token_file = ask("Path to Vault token file (e.g., ~/.vault-token)")
    if args.vault_token_file and not args.vault_token:
        with open(os.path.expanduser(args.vault_token_file), "r") as f: args.vault_token = f.read().strip()
    if not args.issuer: args.issuer = ask("OIDC issuer base URL (e.g., https://your-idp.example.com)")
    if not args.client_id: args.client_id = ask("OIDC client ID")
    if not args.client_secret: args.client_secret = ask("OIDC client secret", secret=True)

    args.vault_addr = normalize_base(args.vault_addr)
    args.issuer = adopt_issuer_from_discovery(args.issuer) 

    verify = False if args.insecure_skip_verify else True
    v = Vault(args.vault_addr, args.vault_token, args.vault_namespace, verify)

    # optional CA bundle
    ca_pem = None
    if args.ca_pem_file:
        with open(os.path.expanduser(args.ca_pem_file), "r") as f: ca_pem = f.read()

    # ensure auth method
    r = v.get("sys/auth"); r.raise_for_status()
    mounts = r.json(); key = args.mount.rstrip("/") + "/"
    if key in mounts:
        t = mounts[key]["type"]; print(f"[auth] mount '{args.mount}' exists (type={t}).")
        if t != "jwt": raise SystemExit(f"Auth mount '{args.mount}' is type '{t}', expected 'jwt'. Choose another --mount or remove it.")
    else:
        print(f"[auth] enabling jwt at '{args.mount}' ...")
        r = v.post(f"sys/auth/{args.mount}", {"type": "jwt"})
        if r.status_code not in (200, 204): raise SystemExit(f"Enable auth failed [{r.status_code}]: {r.text}")
        print("[auth] enabled.")

    # write config
    write_oidc_config(v,args.mount,args.issuer,args.client_id,args.client_secret,args.role,ca_pem)

    # upsert role
    upsert_role(v,args.mount,args.role,args.vault_addr,args.policies,args.groups_claim,args.scopes,args.token_ttl)

    print("\nDone.")
    print(f"Check config: vault read auth/{args.mount}/config")
    print(f"Check role:   vault read auth/{args.mount}/role/{args.role}")
    print(f"Try login:    VAULT_ADDR={args.vault_addr} vault login -method=oidc role={args.role}")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"HTTP error: {e.response.status_code} {e.response.text}", file=sys.stderr); sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
