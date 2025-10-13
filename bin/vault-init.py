#!/usr/bin/env python3

import argparse, json, sys, time
import json, ast
from kubernetes import client, config
from kubernetes.client import V1DeleteOptions
from kubernetes.stream import stream

def k8s():
    config.load_kube_config()
    return client.CoreV1Api()

def list_vault_pods(core, ns, release="vault"):
    lbl = f"app.kubernetes.io/name=vault,app.kubernetes.io/instance={release}"
    pods = core.list_namespaced_pod(ns, label_selector=lbl).items
    names = sorted(p.metadata.name for p in pods)
    print(f"[pods] {', '.join(names)}")
    return names

def wait_container_running(core, ns, pod, timeout=300):
    print(f"[wait] {pod} containers 'running' (not waiting/crashloop). Timeout {timeout}s")
    start = time.time()
    while time.time() - start < timeout:
        p = core.read_namespaced_pod(pod, ns)
        if p.status.phase in ("Running","Succeeded"):
            cs = p.status.container_statuses or []
            if cs and all((c.state.running is not None) for c in cs):
                print(f"[ok] {pod} containers are running")
                return
        time.sleep(2)
    raise SystemExit(f"[timeout] {pod} containers not running in {timeout}s")

def kexec(core, ns, pod, cmd, container="vault", env=None):
    if env:
        exports = " ".join([f'export {k}="{v}";' for k,v in env.items()])
        shell = f"{exports} {cmd}"
    else:
        shell = cmd
    print(f"[exec] {pod}$ {cmd}")
    out = stream(core.connect_get_namespaced_pod_exec, pod, ns,
                 container=container, command=["sh","-lc",shell],
                 stderr=True, stdin=False, stdout=True, tty=False, _preload_content=True)
    print(out.strip())
    return out


def parse_any_json(text: str):
    # First try strict JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # Fallback: accept Python-style dicts (single quotes, True/False/None)
    try:
        obj = ast.literal_eval(text)
        return obj
    except Exception as e:
        raise SystemExit(f"[error] could not parse output as JSON or Python-literal:\n{text}\n{e}")

def vault_status(core, ns, pod):
    out = kexec(core, ns, pod, "vault status -format=json")
    data = parse_any_json(out)
    print(f"[status:{pod}] initialized={data.get('initialized')} sealed={data.get('sealed')} standby={data.get('standby')}")
    return data

def vault_init(core, ns, pod):
    # Auto-seal (gcpckms) => use recovery_* only
    out = kexec(core, ns, pod, "vault operator init -recovery-shares=1 -recovery-threshold=1 -format=json")
    data = parse_any_json(out)
    print("[init] JSON:")
    print(json.dumps(data, indent=2))   # re-emit as proper JSON
    return data

def raft_join(core, ns, pod, leader_addr, token=None):
    env = {"VAULT_ADDR": leader_addr}
    if token: env["VAULT_TOKEN"] = token
    kexec(core, ns, pod, f"vault operator raft join {leader_addr}", env=env)

def follower_env_sanity(core, ns, pod):
    out = kexec(core, ns, pod, 'echo $GOOGLE_APPLICATION_CREDENTIALS; ls -l $GOOGLE_APPLICATION_CREDENTIALS || true')
    print(f"[env:{pod}] {out.strip()}")

def restart_pod(core, ns, pod):
    print(f"[restart] deleting {pod} to trigger auto-unseal via KMS …")
    core.delete_namespaced_pod(name=pod, namespace=ns, body=V1DeleteOptions(grace_period_seconds=0))
    # Wait for it to disappear then reappear running
    # (simple wait loop; reuse your wait_container_running)
    time.sleep(3)
    # Wait until pod name is back (statefulset keeps same name)
    start=time.time()
    while time.time()-start < 300:
        try:
            p = core.read_namespaced_pod(pod, ns); _=p
            if p.status.phase in ("Running","Succeeded"):
                cs = p.status.container_statuses or []
                if cs and all((c.state.running is not None) for c in cs):
                    print(f"[restart] {pod} back and running")
                    return
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit(f"[timeout] follower {pod} did not come back running")

def main():
    ap = argparse.ArgumentParser("Vault bootstrap via kubectl exec (no readiness requirement).")
    ap.add_argument("-n","--namespace", default="infra")
    ap.add_argument("--release", default="vault")
    ap.add_argument("--container", default="vault")
    ap.add_argument("--root-token", default=None)
    ap.add_argument("--addr", default=None, help="Leader VAULT_ADDR (default http://<pod-0>.<release>-internal:8200)")
    ap.add_argument("--replicas", type=int, default=None, help="Force replica count; otherwise discover by labels")
    args = ap.parse_args()

    core = k8s()
    pods = list_vault_pods(core, args.namespace, args.release)
    if not pods: sys.exit("[error] no vault pods found")
    if args.replicas is not None: pods = pods[:args.replicas]

    leader_pod = sorted(pods)[0]
    leader_addr = args.addr or f"http://{leader_pod}.{args.release}-internal:8200"
    print(f"[leader] {leader_pod}  VAULT_ADDR={leader_addr}")

    # Only require 'Running', not 'Ready'
    wait_container_running(core, args.namespace, leader_pod)

    st = vault_status(core, args.namespace, leader_pod)
    if not st.get("initialized"):
        print("[do] initializing vault …")
        vault_init(core, args.namespace, leader_pod)
        # give raft a sec to settle
        time.sleep(3)
    else:
        print("[skip] already initialized")

    # Join followers (wait for running, then join)
    for p in pods:
        if p == leader_pod: continue
        wait_container_running(core, args.namespace, p)
        follower_env_sanity(core, args.namespace, p)
        try:
            raft_join(core, args.namespace, p, leader_addr, token=args.root_token)
        except Exception as e:
            print(f"[warn] join failed for {p}: {e}")

        # poll status; restart if still sealed/uninitialized
        time.sleep(2)
        st = vault_status(core, args.namespace, p)
        if not st.get("initialized") or st.get("sealed"):
            restart_pod(core, args.namespace, p)
            time.sleep(2)
            st = vault_status(core, args.namespace, p)

    # Final statuses
    for p in pods:
        vault_status(core, args.namespace, p)

if __name__ == "__main__":
    main()
