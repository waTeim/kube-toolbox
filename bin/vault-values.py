#!/usr/bin/env python3
"""
Render Vault values.yaml for hashicorp/vault chart v0.31.x

Features:
- standalone disabled; HA + Raft enabled
- HCL under server.ha.raft.config:
    * optional api_addr
    * ui = true
    * IPv4 listener
    * storage "raft" with retry_join -> http://<release>-0.<release>-internal:8200
    * service_registration "kubernetes"
    * disable_mlock = true
    * seal "gcpckms" (project/location/keyring/keyname)
- Mount GCP SA secret and set GOOGLE_APPLICATION_CREDENTIALS
- Optional ingress
- Replicas
- If --ingress-host is set and --api-addr is not, api_addr defaults to https://<ingress-host>

Input “facts” YAML must include:
gcp:
  project: <id>
  location: <gcp-location>
  keyring: <kms-keyring>
  keyname: <kms-key>
k8s:
  secretName: vault-gcp
  mountPath: /vault/userconfig/gcp
  credsFile: /vault/userconfig/gcp/vault-gcp/creds.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# --- YAML literal helper so HCL renders as a block (no \n escapes)
class _LiteralStr(str):
    pass


def _repr_literal(dumper: yaml.Dumper, data: _LiteralStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(_LiteralStr, _repr_literal)
yaml.add_representer(_LiteralStr, _repr_literal, Dumper=yaml.SafeDumper)


def load_cfg(path: Optional[str]) -> Dict[str, Any]:
    if path and path != "-":
        text = Path(path).read_text()
    else:
        text = sys.stdin.read()
    obj = yaml.safe_load(text) or {}
    if not isinstance(obj, dict):
        raise SystemExit("error: input must be a YAML mapping")
    return obj


def dump_yaml(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False)


def build_values(
    facts: Dict[str, Any],
    release: str,
    replicas: int,
    ingress_host: Optional[str],
    ingress_class: str,
    ingress_tls_secret: str,
    api_addr: Optional[str],
) -> Dict[str, Any]:
    gcp = facts.get("gcp") or {}
    k8s = facts.get("k8s") or {}

    for k in ("project", "location", "keyring", "keyname"):
        if not gcp.get(k):
            raise SystemExit(f"error: missing gcp.{k}")

    for k in ("secretName", "mountPath", "credsFile"):
        if not k8s.get(k):
            raise SystemExit(f"error: missing k8s.{k}")

    # Default api_addr from ingress host if not explicitly set
    if not api_addr and ingress_host:
        api_addr = f"https://{ingress_host}"

    leader_api = f"http://{release}-0.{release}-internal:8200"
    api_line = f'api_addr = "{api_addr}"\n\n' if api_addr else ""

    hcl = _LiteralStr(
        f"""{api_line}ui = true

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
"""
    )

    ingress_enabled = bool(ingress_host)
    ingress = {
        "enabled": ingress_enabled,
        "ingressClassName": ingress_class,
        "pathType": "Prefix",
        "hosts": [{"host": ingress_host, "paths": ["/"]}] if ingress_enabled else [],
        "tls": [{"secretName": ingress_tls_secret, "hosts": [ingress_host]}] if ingress_enabled else [],
    }

    extra_env = {"GOOGLE_APPLICATION_CREDENTIALS": k8s["credsFile"]}
    if api_addr:
        extra_env["VAULT_API_ADDR"] = api_addr

    values: Dict[str, Any] = {
        "server": {
            "standalone": {"enabled": False},
            "ha": {
                "enabled": True,
                "raft": {
                    "enabled": True,
                    "config": hcl,
                },
            },
            "ui": {
                "enabled": True,
                "serviceType": "ClusterIP",
                "externalPort": 8200,
            },
            "ingress": ingress,
            "extraEnvironmentVars": extra_env,
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
    ap = argparse.ArgumentParser(
        description="Render Vault values.yaml for hashicorp/vault chart v0.31.x (HA Raft + GCP KMS + retry_join)."
    )
    ap.add_argument("--config", default="-", help="Minimal facts YAML (default: stdin)")
    ap.add_argument("--out", default="-", help="Output file (default: stdout)")
    ap.add_argument("--release", default="vault", help="Helm release name (default: vault)")
    ap.add_argument("--replicas", type=int, default=3, help="Vault replicas (default: 3)")
    ap.add_argument("--ingress-host", default="", help="Ingress host (if set, enables ingress)")
    ap.add_argument("--ingress-class", default="nginx", help="Ingress className (default: nginx)")
    ap.add_argument("--ingress-tls-secret", default="vault-tls", help="Ingress TLS secret (default: vault-tls)")
    ap.add_argument(
        "--api-addr",
        default="",
        help='Public API address (e.g., "https://vault.example.com"). '
             "Defaults to https://<ingress-host> when --ingress-host is set.",
    )
    args = ap.parse_args()

    facts = load_cfg(args.config)
    values = build_values(
        facts=facts,
        release=args.release,
        replicas=args.replicas,
        ingress_host=(args.ingress_host.strip() or None),
        ingress_class=args.ingress_class,
        ingress_tls_secret=args.ingress_tls_secret,
        api_addr=(args.api_addr.strip() or None),
    )

    out_text = dump_yaml(values)
    if args.out == "-" or not args.out:
        sys.stdout.write(out_text)
    else:
        Path(args.out).write_text(out_text)
        print(f"Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
