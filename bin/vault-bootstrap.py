#!/usr/bin/env python3
import argparse, json, sys, time
from kubernetes import client, config
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

def vault_status(core, ns, pod):
    out = kexec(core, ns, pod, "vault status -format=json")
    try:
        j = json.loads(out)
    except Exception:
        j = {}
    print(f"[status:{pod}] initialized={j.get('initialized')} sealed={j.get('sealed')} standby={j.get('standby')}")
    return j

def vault_init(core, ns, pod):
    # Auto-seal (gcpckms) => use recovery_* only
    out = kexec(core, ns, pod, "vault operator init -recovery-shares=1 -recovery-threshold=1 -format=json")
    try:
        j = json.loads(out)
    except Exception as e:
        raise SystemExit(f"[error] init did not return JSON\n{out}\n{e}")
    print("[init] JSON:")
    print(json.dumps(j, indent=2))
    return j

def raft_join(core, ns, pod, leader_addr, token=None):
    env = {"VAULT_ADDR": leader_addr}
    if token: env["VAULT_TOKEN"] = token
    kexec(core, ns, pod, f"vault operator raft join {leader_addr}", env=env)

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
        try:
            raft_join(core, args.namespace, p, leader_addr, token=args.root_token)
        except Exception as e:
            print(f"[warn] join failed for {p}: {e}")

    # Final statuses
    for p in pods:
        vault_status(core, args.namespace, p)

if __name__ == "__main__":
    main()
