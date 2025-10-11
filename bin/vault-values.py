#!/usr/bin/env python3
"""
Render a Vault Helm values.yaml for chart v0.31.x with:
- standalone disabled
- HA + Raft enabled
- HCL under server.ha.raft.config including:
    * ui = true
    * IPv4 listener (no IPv6)
    * storage "raft" with retry_join to leader
    * service_registration "kubernetes"
    * disable_mlock = true
    * seal "gcpckms" using values from a minimal config (see below)
- Google SA JSON mounted & GOOGLE_APPLICATION_CREDENTIALS set
- Optional ingress config
- Replicas

INPUT (via --config or stdin) is the minimal “facts” YAML like:
gcp:
  project: secrets-474504
  location: global
  keyring: vault-unseal-ring
  keyname: vault-unseal-key
k8s:
  secretName: vault-gcp
  mountPath: /vault/userconfig/gcp
  credsFile: /vault/userconfig/gcp/vault-gcp/creds.json

USAGE:
  ./render_vault_values_v031.py --config facts.yaml --release vault --ingress-host vault.example.com > values.yaml
"""
import argparse, sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print("PyYAML required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# --- YAML literal helper (so the HCL renders cleanly, not as \"\\n\")
class _LiteralStr(str): pass
def _repr_literal(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
yaml.add_representer(_LiteralStr, _repr_literal)
yaml.add_representer(_LiteralStr, _repr_literal, Dumper=yaml.SafeDumper)

def load_cfg(path: str | None):
    text = Path(path).read_text() if path and path != "-" else sys.stdin.read()
    obj = yaml.safe_load(text) or {}
    if not isinstance(obj, dict):
        raise SystemExit("error: input must be a YAML mapping")
    return obj

def dump_yaml(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False)

def build_values(facts: dict, release: str, replicas: int, ingress_host: str | None, ingress_class: str, ingress_tls_secret: str) -> dict:
    gcp = facts.get("gcp") or {}
    k8s = facts.get("k8s") or {}

    # Validate required inputs
    for k in ("project","location","keyring","keyname"):
        if not gcp.get(k): raise SystemExit(f"error: missing gcp.{k}")
    for k in ("secretName","mountPath","credsFile"):
        if not k8s.get(k): raise SystemExit(f"error: missing k8s.{k}")

    leader_api = f"http://{release}-0.{release}-internal:8200"

    # Raw HCL placed under server.ha.raft.config (chart v0.31.x)
    hcl = _LiteralStr(
f"""ui = true

listener "tcp" {{
  tls_disable     = 1
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
}}

storage "raft" {{
  path = "/vault/data"

  retry_join {{
    leader_api_addr = "{leader_api}"
  }}
}}

service_registration "kubernetes" {{}}

disable_mlock = true

seal "gcpckms" {{
  project    = "{gcp["project"]}"
  region     = "{gcp["location"]}"
  key_ring   = "{gcp["keyring"]}"
  crypto_key = "{gcp["keyname"]}"
}}
""")

    ingress_enabled = bool(ingress_host)
    ingress = {
        "enabled": ingress_enabled,
        "ingressClassName": ingress_class,
        "pathType": "Prefix",
        "hosts": [{"host": ingress_host, "paths": ["/"]}] if ingress_enabled else [],
        "tls": [{"secretName": ingress_tls_secret, "hosts": [ingress_host]}] if ingress_enabled else []
    }

    values = {
        "server": {
            "standalone": {"enabled": False},
            "ha": {
                "enabled": True,
                "raft": {
                    "enabled": True,
                    "config": hcl,        # <— the working HCL block
                },
            },
            "ui": {
                "enabled": True,
                "serviceType": "ClusterIP",
                "externalPort": 8200,
            },
            "ingress": ingress,
            "extraEnvironmentVars": {
                "GOOGLE_APPLICATION_CREDENTIALS": k8s["credsFile"],
            },
            "extraVolumes": [
                {"type": "secret", "name": k8s["secretName"], "path": k8s["mountPath"]},
            ],
            "extraVolumeMounts": [
                {"name": k8s["secretName"], "mountPath": k8s["mountPath"], "readOnly": True},
            ],
            "replicas": int(replicas),
        },
        "serviceAccount": {"create": True},
    }
    return values

def main():
    ap = argparse.ArgumentParser(description="Render Vault values.yaml for hashicorp/vault chart v0.31.x (HA Raft + GCP KMS).")
    ap.add_argument("--config", default="-", help="Minimal facts YAML (default: stdin)")
    ap.add_argument("--out", default="-", help="Output file (default: stdout)")
    ap.add_argument("--release", default="vault", help="Helm release name (default: vault)")
    ap.add_argument("--replicas", type=int, default=3, help="Vault replicas (default: 3)")
    ap.add_argument("--ingress-host", default="", help="Ingress host (if set, enables ingress)")
    ap.add_argument("--ingress-class", default="nginx", help="Ingress className (default: nginx)")
    ap.add_argument("--ingress-tls-secret", default="vault-tls", help="Ingress TLS secret (default: vault-tls)")
    args = ap.parse_args()

    facts = load_cfg(args.config)
    values = build_values(
        facts=facts,
        release=args.release,
        replicas=args.replicas,
        ingress_host=args.ingress_host.strip() or None,
        ingress_class=args.ingress_class,
        ingress_tls_secret=args.ingress_tls_secret,
    )
    out_text = dump_yaml(values)
    if args.out == "-" or not args.out:
        sys.stdout.write(out_text)
    else:
        Path(args.out).write_text(out_text)
        print(f"Wrote {args.out}", file=sys.stderr)

if __name__ == "__main__":
    main()
