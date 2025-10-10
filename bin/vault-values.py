#!/usr/bin/env python3
import argparse, sys
from pathlib import Path

class _LiteralStr(str): pass
def _repr_literal(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")

def _load_cfg(p):
    import yaml
    if p and p != "-": return yaml.safe_load(Path(p).read_text())
    return yaml.safe_load(sys.stdin.read())

def _dump_yaml(data):
    import yaml
    yaml.add_representer(_LiteralStr, _repr_literal)
    yaml.add_representer(_LiteralStr, _repr_literal, Dumper=yaml.SafeDumper)
    return yaml.safe_dump(data, sort_keys=False)

def main():
    try:
        import yaml  # noqa
    except Exception:
        print("PyYAML required. Install: pip install pyyaml", file=sys.stderr); sys.exit(1)

    ap = argparse.ArgumentParser(
        description="Render Vault Helm values.yaml. Disables standalone, enables HA/Raft, and injects a raw HA config with storage+seal."
    )
    ap.add_argument("--config", default="-", help="Input minimal config YAML (from gcpkms-to-vault-config.py). Default: '-' (stdin)")
    ap.add_argument("--out", default="-", help="Output values.yaml. Default: '-' (stdout)")
    ap.add_argument("--replicas", type=int, default=3, help="Vault replicas (default: 3)")
    ap.add_argument("--ingress-host", default="", help="Ingress host (if set, enables Ingress)")
    ap.add_argument("--ingress-class", default="nginx", help="Ingress className (default: nginx)")
    ap.add_argument("--ingress-tls-secret", default="vault-tls", help="Ingress TLS secret name (default: vault-tls)")
    args = ap.parse_args()

    cfg = _load_cfg(args.config)
    if not isinstance(cfg, dict):
        print("error: input YAML must be a mapping/object", file=sys.stderr); sys.exit(2)

    gcp = cfg.get("gcp") or {}
    k8s = cfg.get("k8s") or {}
    for k in ("project","location","keyring","keyname"):
        if not gcp.get(k): sys.exit(f"error: missing gcp.{k}")
    for k in ("secretName","mountPath","credsFile"):
        if not k8s.get(k): sys.exit(f"error: missing k8s.{k}")

    # Single raw HA config with storage + service_registration + seal
    ha_raw = _LiteralStr(f"""ui = true

storage "raft" {{
  path = "/vault/data"
}}

service_registration "kubernetes" {{}}

seal "gcpckms" {{
  project    = "{gcp["project"]}"
  region     = "{gcp["location"]}"
  key_ring   = "{gcp["keyring"]}"
  crypto_key = "{gcp["keyname"]}"
}}
""")

    ingress_enabled = bool(args.ingress_host)
    ingress = {
        "enabled": ingress_enabled,
        "ingressClassName": args.ingress_class,
        "pathType": "Prefix",
        "hosts": [{"host": args.ingress_host, "paths": ["/"]}] if ingress_enabled else [],
        "tls": [{"secretName": args.ingress_tls_secret, "hosts": [args.ingress_host]}] if ingress_enabled else []
    }

    values = {
        "server": {
            "standalone": { "enabled": False },
            "ha": {
                "enabled": True,
                "raft": { "enabled": True },  # PVCs etc handled by chart
                "config": ha_raw              # <-- raw HCL ensures storage+seal are present
            },
            "ui": { "enabled": True, "serviceType": "ClusterIP", "externalPort": 8200 },
            "ingress": ingress,
            "extraEnvironmentVars": { "GOOGLE_APPLICATION_CREDENTIALS": k8s["credsFile"] },
            "extraVolumes": [ { "type": "secret", "name": k8s["secretName"], "path": k8s["mountPath"] } ],
            "extraVolumeMounts": [ { "name": k8s["secretName"], "mountPath": k8s["mountPath"], "readOnly": True } ],
            "replicas": int(args.replicas),
        },
        "serviceAccount": { "create": True }
    }

    out_text = _dump_yaml(values)
    if args.out == "-" or not args.out:
        sys.stdout.write(out_text)
    else:
        Path(args.out).write_text(out_text)
        print(f"Wrote Helm values to {args.out}", file=sys.stderr)

if __name__ == "__main__":
    main()
