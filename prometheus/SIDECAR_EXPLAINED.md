# Grafana Sidecar Feature Explained

## What is the Sidecar?

The Grafana sidecar is a **separate container** that runs alongside Grafana in the same pod. It watches for Kubernetes ConfigMaps and automatically loads them into Grafana.

Think of it as an auto-sync mechanism for **GitOps workflows**.

## What You Already Have

Your current config:
```yaml
sidecar:
  dashboards:
    enabled: true
    searchNamespace: ALL
  datasources:
    enabled: true
    maxLines: 1000
```

✅ I've preserved this in the new values files with improvements.

## Why It's Important

### Without Sidecar:
1. Create dashboard in Grafana UI
2. Dashboard stored only in Grafana database
3. To backup: manually export JSON
4. To restore: manually import JSON
5. No version control
6. Manual process for every dashboard

### With Sidecar:
1. Create dashboard JSON in Git
2. Apply as ConfigMap to Kubernetes
3. **Sidecar automatically loads it into Grafana**
4. Version controlled ✓
5. Automated ✓
6. Survives Grafana restarts ✓

## How It Works

```
┌─────────────────────────────────────┐
│         Grafana Pod                 │
│  ┌──────────────┐  ┌─────────────┐ │
│  │   Grafana    │  │   Sidecar   │ │
│  │  Container   │←─│  Container  │ │
│  └──────────────┘  └──────┬──────┘ │
└────────────────────────────│────────┘
                             │
                             │ watches
                             ↓
                    ┌────────────────┐
                    │   ConfigMaps   │
                    │  (k8s cluster) │
                    └────────────────┘
```

The sidecar:
1. **Watches** for ConfigMaps with specific labels
2. **Detects** changes (create/update/delete)
3. **Syncs** dashboards/datasources to Grafana
4. **Updates** automatically when ConfigMaps change

## Configuration in Your Values

```yaml
grafana:
  sidecar:
    dashboards:
      enabled: true                    # Enable dashboard sidecar
      searchNamespace: ALL             # Look in all namespaces
      label: grafana_dashboard         # ConfigMap label to watch
      provider:
        allowUiUpdates: true           # Allow editing in Grafana UI
    
    datasources:
      enabled: true                    # Enable datasource sidecar
      searchNamespace: ALL             # Look in all namespaces
      label: grafana_datasource        # ConfigMap label to watch
```

## Example: Dashboard as ConfigMap

### Create a Dashboard ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-awesome-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"    # This label is what sidecar watches for!
data:
  my-dashboard.json: |
    {
      "dashboard": {
        "title": "My Awesome Dashboard",
        "panels": [
          {
            "title": "CPU Usage",
            "targets": [
              {
                "expr": "rate(container_cpu_usage_seconds_total[5m])"
              }
            ]
          }
        ]
      }
    }
```

Apply it:
```bash
kubectl apply -f my-dashboard-configmap.yaml
```

**Within seconds**, the dashboard appears in Grafana automatically! 🎉

## Example: Datasource as ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-datasource
  namespace: monitoring
  labels:
    grafana_datasource: "1"
data:
  prometheus.yaml: |
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        access: proxy
        url: http://kube-prom-stack-prometheus:9090
        isDefault: true
```

## Practical Use Cases

### 1. **GitOps Workflow**

```bash
# Store dashboards in Git
git-repo/
  └── dashboards/
      ├── kubernetes-overview.yaml
      ├── application-metrics.yaml
      └── infrastructure.yaml

# Apply to cluster
kubectl apply -f dashboards/

# Automatically loaded by sidecar! ✓
```

### 2. **Team Dashboards**

```yaml
# Each team manages their own dashboards
apiVersion: v1
kind: ConfigMap
metadata:
  name: team-alpha-dashboards
  namespace: team-alpha
  labels:
    grafana_dashboard: "1"
    team: alpha
data:
  # Team Alpha's dashboards
```

Because `searchNamespace: ALL`, Grafana finds dashboards in any namespace.

### 3. **Environment-Specific Dashboards**

```yaml
# dev-dashboards.yaml
metadata:
  name: dev-dashboards
  namespace: dev
  labels:
    grafana_dashboard: "1"
    environment: dev
---
# prod-dashboards.yaml
metadata:
  name: prod-dashboards
  namespace: prod
  labels:
    grafana_dashboard: "1"
    environment: prod
```

### 4. **Export Your Current Dashboards to ConfigMaps**

After using the Python script to export:

```bash
# Export dashboards
./export_grafana_dashboards.py

# Convert to ConfigMaps (example script)
for file in grafana-dashboards-backup-*/General/*.json; do
  name=$(basename "$file" .json)
  kubectl create configmap "dashboard-${name}" \
    --from-file="$file" \
    --namespace=monitoring \
    --dry-run=client -o yaml | \
  kubectl label --local -f - \
    grafana_dashboard=1 \
    --dry-run=client -o yaml | \
  kubectl apply -f -
done
```

## Sidecar vs. Persistence

| Feature | Sidecar (ConfigMaps) | Persistence (PVC) |
|---------|---------------------|-------------------|
| **Storage** | ConfigMaps in K8s | Database on PV |
| **Version Control** | ✅ Git-friendly | ❌ Database blob |
| **Automation** | ✅ Auto-sync | ❌ Manual |
| **Survives pod restart** | ✅ Yes | ✅ Yes |
| **Survives cluster rebuild** | ✅ If in Git | ⚠️ If PV retained |
| **Edit in UI** | ✅ Yes (with allowUiUpdates) | ✅ Yes |
| **Use Case** | GitOps, Infrastructure dashboards | User-created dashboards |

**Best Practice**: Use **both**!
- Sidecar for infrastructure/team dashboards (ConfigMaps)
- Persistence for user-created ad-hoc dashboards (PVC)

## Your Current Setup Migration

Your old config had:
```yaml
sidecar:
  dashboards:
    enabled: true
    searchNamespace: ALL
  datasources:
    enabled: true
    maxLines: 1000
```

New config has:
```yaml
sidecar:
  dashboards:
    enabled: true
    searchNamespace: ALL
    label: grafana_dashboard              # ← More explicit
    provider:
      allowUiUpdates: true                # ← Allows UI editing
  datasources:
    enabled: true
    searchNamespace: ALL
    label: grafana_datasource             # ← More explicit
```

✅ **All your sidecar functionality is preserved!**

## Check if You Have Existing ConfigMaps

```bash
# Check for dashboard ConfigMaps
kubectl get configmaps -A -l grafana_dashboard=1

# Check for datasource ConfigMaps
kubectl get configmaps -A -l grafana_datasource=1
```

If you have any, they'll automatically load into your new Grafana!

## Advanced: Organizing Dashboards

You can organize dashboards into folders:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kubernetes-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "Kubernetes"  # ← Creates/uses this folder
data:
  k8s-cluster.json: |
    { ... }
  k8s-nodes.json: |
    { ... }
```

## Summary

✅ **Sidecar is enabled** in your new values files  
✅ **Same functionality** as your current setup  
✅ **Enhanced with** explicit labels and UI editing  
✅ **Searches ALL namespaces** for dashboards  
✅ **Automatically syncs** ConfigMaps to Grafana  

The sidecar is a **key feature** for modern GitOps workflows. It's not going away - it's getting better! 🚀

## Migration Impact

When you migrate with PV reuse:
1. **PVC dashboards** ✓ preserved (on PV)
2. **ConfigMap dashboards** ✓ work immediately (sidecar loads them)
3. **Best of both worlds** ✓

You get both persistence AND automation!
