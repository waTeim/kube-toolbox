#!/usr/bin/env python3
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

def need(bin_name):
    if shutil.which(bin_name) is None:
        sys.exit(f"ERROR: required binary not found on PATH: {bin_name}")

def run(cmd, *, check=True, capture=False):
    kw = dict(text=True)
    if capture:
        kw["stdout"] = subprocess.PIPE
        kw["stderr"] = subprocess.PIPE
    p = subprocess.run(cmd, **kw)
    if check and p.returncode != 0:
        msg = f"Command failed ({p.returncode}): {' '.join(cmd)}\n"
        if capture:
            msg += f"STDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}\n"
        sys.exit(msg)
    return p

def ensure_gcloud_login():
    p = run(["gcloud","auth","list","--format=value(account)"], capture=True, check=False)
    accounts = [a.strip() for a in p.stdout.splitlines() if a.strip()]
    if not accounts:
        print("No active gcloud account. Launching 'gcloud auth login'…", file=sys.stderr)
        run(["gcloud","auth","login"])
        p = run(["gcloud","auth","list","--format=value(account)"], capture=True)
        accounts = [a.strip() for a in p.stdout.splitlines() if a.strip()]
    active = run(["gcloud","config","get-value","account"], capture=True, check=False).stdout.strip()
    if active in ("","(unset)"):
        chosen = accounts[0] if len(accounts)==1 else _pick("Select a gcloud account", accounts)
        run(["gcloud","config","set","account",chosen], capture=True)
        active = chosen
    return active

def _pick(prompt, options):
    print(prompt + ":", file=sys.stderr)
    for i,o in enumerate(options,1):
        print(f"  {i}) {o}", file=sys.stderr)
    while True:
        sel = input("Enter number: ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(options):
            return options[int(sel)-1]

def resolve_project_id(identifier: str) -> str:
    ok = subprocess.run(["gcloud","projects","describe",identifier], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True).returncode == 0
    if ok: return identifier
    p = run(["gcloud","projects","list","--filter",f"name={identifier}","--format","value(projectId)"], capture=True, check=False)
    ids = [x.strip() for x in p.stdout.splitlines() if x.strip()]
    if len(ids)==1: return ids[0]
    if len(ids)>1: sys.exit("Multiple projects share that display name. Use one of these IDs:\n  " + "\n  ".join(ids))
    sys.exit(f"Project not found: '{identifier}'. Try: gcloud projects list")

def exists_keyring(project, location, keyring):
    return subprocess.run(["gcloud","kms","keyrings","describe",keyring,"--location",location,f"--project={project}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True).returncode==0
def exists_key(project, location, keyring, keyname):
    return subprocess.run(["gcloud","kms","keys","describe",keyname,"--location",location,"--keyring",keyring,f"--project={project}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True).returncode==0
def exists_sa(project, sa_email):
    return subprocess.run(["gcloud","iam","service-accounts","describe",sa_email,f"--project={project}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True).returncode==0

def ensure_keyring(project, location, keyring):
    if not exists_keyring(project, location, keyring):
        run(["gcloud","kms","keyrings","create",keyring,"--location",location,f"--project={project}"], capture=True)
def ensure_key(project, location, keyring, keyname):
    if not exists_key(project, location, keyring, keyname):
        run(["gcloud","kms","keys","create",keyname,"--location",location,"--keyring",keyring,"--purpose","encryption",f"--project={project}"], capture=True)
def ensure_sa(project, sa_email, sa_name):
    if not exists_sa(project, sa_email):
        run(["gcloud","iam","service-accounts","create",sa_name,"--display-name","Vault auto-unseal",f"--project={project}"], capture=True)
def ensure_kms_binding(project, location, keyring, keyname, sa_email):
    pol = run(["gcloud","kms","keys","get-iam-policy",keyname,"--location",location,"--keyring",keyring,f"--project={project}","--format=json"], capture=True)
    j = json.loads(pol.stdout or "{}")
    already = any(b.get("role")=="roles/cloudkms.cryptoKeyEncrypterDecrypter" and f"serviceAccount:{sa_email}" in set(b.get("members",[])) for b in j.get("bindings",[]))
    if not already:
        run(["gcloud","kms","keys","add-iam-policy-binding",keyname,"--location",location,"--keyring",keyring,f"--project={project}","--member",f"serviceAccount:{sa_email}","--role","roles/cloudkms.cryptoKeyEncrypterDecrypter"], capture=True)

def current_namespace_from_kubeconfig():
    try:
        from kubernetes import config
        contexts, active = config.list_kube_config_contexts()
        if not active: return "default"
        return active["context"].get("namespace","default")
    except Exception:
        return "default"

def ensure_namespace(api, name):
    from kubernetes.client import V1Namespace, V1ObjectMeta
    try:
        api.read_namespace(name)
    except Exception:
        api.create_namespace(V1Namespace(metadata=V1ObjectMeta(name=name)))

def create_or_replace_secret(api, namespace, name, string_data_dict):
    from kubernetes.client import V1Secret, V1ObjectMeta
    sec = V1Secret(metadata=V1ObjectMeta(name=name, namespace=namespace), type="Opaque", string_data=string_data_dict)
    try:
        api.create_namespaced_secret(namespace, sec)
    except Exception:
        api.replace_namespaced_secret(name, namespace, sec)

def to_yaml(d):
    try:
        import yaml
        return yaml.safe_dump(d, sort_keys=False)
    except Exception:
        import json as _json
        return _json.dumps(d, indent=2)

def main():
    need("gcloud")
    ap = argparse.ArgumentParser(description="Ensure GCP KMS + SA (idempotent), optional K8s Secret, and emit minimal config YAML (gcp + k8s).")
    ap.add_argument("--project", required=True, help="GCP project (ID or display name)")
    ap.add_argument("--location", default="global", help="KMS location (global or region)")
    ap.add_argument("--keyring", default="vault-unseal-ring", help="KMS key ring")
    ap.add_argument("--keyname", default="vault-unseal-key", help="KMS key name")
    ap.add_argument("--sa-name", default="vault-unseal", help="Service Account name (no domain)")
    ap.add_argument("--namespace", default=None, help="K8s namespace for Secret (defaults to current context)")
    ap.add_argument("--secret-name", default="vault-gcp", help="K8s Secret name to hold SA JSON")
    ap.add_argument("--secret-file-name", default="creds.json", help="Filename inside the Secret (default: creds.json)")
    ap.add_argument("--mount-path", default="/vault/userconfig/gcp", help="Mount path in Vault pod")
    ap.add_argument("--create-k8s-secret", action="store_true", help="Create/update the K8s Secret with SA JSON using Python k8s client")
    ap.add_argument("--out", default="-", help="Output file for the minimal config (default: '-' for stdout)")
    args = ap.parse_args()

    acct = ensure_gcloud_login()
    print(f"Using gcloud account: {acct}", file=sys.stderr)

    project_id = resolve_project_id(args.project)
    print(f"Using GCP project: {project_id}", file=sys.stderr)
    run(["gcloud","config","set","project",project_id], capture=True)

    run(["gcloud","services","enable","cloudkms.googleapis.com"], capture=True)
    ensure_keyring(project_id, args.location, args.keyring)
    ensure_key(project_id, args.location, args.keyring, args.keyname)
    sa_email = f"{args.sa_name}@{project_id}.iam.gserviceaccount.com"
    ensure_sa(project_id, sa_email, args.sa_name)
    ensure_kms_binding(project_id, args.location, args.keyring, args.keyname, sa_email)

    ns = args.namespace or current_namespace_from_kubeconfig()

    # Compose the *actual* in-pod path the chart will use (secret mounts under a subdir named after the secret)
    creds_file_in_pod = f"{args.mount_path}/{args.secret_name}/{args.secret_file_name}"

    if args.create_k8s_secret:
        try:
            from kubernetes import client as k8s_client, config as k8s_config
        except Exception:
            sys.exit("ERROR: 'kubernetes' package required for --create-k8s-secret. Install: pip install kubernetes")
        k8s_config.load_kube_config()
        core = k8s_client.CoreV1Api()
        ensure_namespace(core, ns)
        tmp = Path(tempfile.gettempdir()) / "vault-unseal-sa.json"
        if tmp.exists(): tmp.unlink()
        run(["gcloud","iam","service-accounts","keys","create",str(tmp),"--iam-account",sa_email], capture=True)
        sa_json = tmp.read_text()
        try: tmp.unlink()
        except Exception: pass
        create_or_replace_secret(core, ns, args.secret_name, {args.secret_file_name: sa_json})
        print(f"Created/updated Secret '{args.secret_name}' in namespace '{ns}' with file '{args.secret_file_name}'", file=sys.stderr)

    # Minimal config (renderer will add ingress/replicas)
    config_obj = {
        "gcp": {"project": project_id, "location": args.location, "keyring": args.keyring, "keyname": args.keyname},
        "k8s": {"namespace": ns, "secretName": args.secret_name, "mountPath": args.mount_path, "credsFile": creds_file_in_pod}
    }

    out_yaml = to_yaml(config_obj)
    if args.out == "-" or not args.out:
        sys.stdout.write(out_yaml)
    else:
        Path(args.out).write_text(out_yaml)
        print(f"Wrote config to {args.out}", file=sys.stderr)
        print(f"(Namespace: {ns})", file=sys.stderr)

if __name__ == "__main__":
    main()
