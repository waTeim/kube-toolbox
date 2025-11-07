# Python Scripts - Quick Usage Guide

## 📦 Scripts Provided

1. **export_grafana_dashboards.py** - Export all Grafana dashboards
2. **check_grafana_pvc.py** - Check your current Grafana PVC size

Both scripts are pure Python 3 with no external dependencies (uses only stdlib).

---

## 🔍 Check Your Current PVC Size

First, let's see how big your current Grafana PVC is:

```bash
# Default (checks prometheus-grafana in infra namespace)
./check_grafana_pvc.py

# Or specify namespace and PVC name
./check_grafana_pvc.py --namespace infra --pvc prometheus-grafana
```

**Example Output:**
```
[INFO] ==================================================
[INFO] Grafana PVC Size Check
[INFO] ==================================================

[INFO] Checking PVC: prometheus-grafana in namespace: infra
[INFO] PVC Status: Bound
[INFO] Requested Size: 10Gi
[INFO] Actual Size: 10Gi
[INFO] Storage Class: gp3
[INFO] Bound PV: pvc-abc123...

[INFO] Checking PV: pvc-abc123...
[INFO] PV Reclaim Policy: Delete
[WARN] ⚠️  PV reclaim policy is 'Delete', not 'Retain'
[WARN]    Data may be lost if PVC is deleted!

[INFO] ✓ PVC has helm.sh/resource-policy: keep annotation

[INFO] Disk Usage:
---
Filesystem      Size  Used Avail Use% Mounted on
/dev/xvdf       9.8G  2.1G  7.7G  22% /var/lib/grafana
---

[INFO] ==================================================
[INFO] Recommendations
[INFO] ==================================================
[WARN] Current size (10Gi) is quite small
[INFO] Recommended: At least 10Gi for production use
[INFO] Suggested: 30Gi for the new deployment
```

This tells you:
- ✅ Current PVC size
- ✅ How much is actually used
- ✅ Whether it has retention annotations
- ✅ Recommendations for new deployment

---

## 📤 Export Your Dashboards

### Method 1: Interactive (Easiest)

```bash
# Port-forward to current Grafana
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &

# Create API key in Grafana:
# 1. Open http://localhost:3000
# 2. Login
# 3. Configuration → API Keys → Add API Key
# 4. Name: backup, Role: Admin
# 5. Copy the key

# Export dashboards
./export_grafana_dashboards.py --api-key YOUR_API_KEY_HERE

# Kill port-forward when done
pkill -f "port-forward.*grafana"
```

### Method 2: Using Environment Variables

```bash
# Set environment variables
export GRAFANA_URL="http://localhost:3000"
export GRAFANA_API_KEY="your-api-key-here"

# Run export
./export_grafana_dashboards.py

# Output goes to: ./grafana-dashboards-backup-TIMESTAMP/
```

### Method 3: Custom Output Directory

```bash
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key YOUR_KEY \
  --output /path/to/backup
```

### Method 4: Remote Grafana

```bash
# If you can access Grafana remotely (e.g., via ingress)
./export_grafana_dashboards.py \
  --url https://grafana.wat.im \
  --api-key YOUR_KEY
```

**Example Output:**
```
[INFO] Starting Grafana dashboard export...
[INFO] Grafana URL: http://localhost:3000
[INFO] Output directory: ./grafana-dashboards-backup-20241105-143022
[INFO] Testing connection to Grafana...
[INFO] ✓ Connected to Grafana (Org: Main Org.)
[INFO] Fetching list of dashboards...
[INFO] Found 15 dashboards to export
[INFO] [1/15] Exporting: General/Kubernetes Cluster (UID: k8s-cluster)
[INFO]   ✓ Exported to: grafana-dashboards-backup-20241105-143022/General/Kubernetes_Cluster_k8s-cluster.json
[INFO] [2/15] Exporting: Monitoring/Node Exporter (UID: node-exp)
[INFO]   ✓ Exported to: grafana-dashboards-backup-20241105-143022/Monitoring/Node_Exporter_node-exp.json
...
[INFO] Manifest file created: grafana-dashboards-backup-20241105-143022/manifest.txt
[INFO] ========================================
[INFO] Export Summary
[INFO] ========================================
[INFO] Total dashboards: 15
[INFO] Successfully exported: 15
[INFO] Output directory: ./grafana-dashboards-backup-20241105-143022
[INFO] ========================================
[INFO] Backup complete! ✓
```

---

## 📁 What Gets Created

After export:
```
grafana-dashboards-backup-20241105-143022/
├── General/
│   ├── Dashboard1_uid1.json
│   └── Dashboard2_uid2.json
├── Monitoring/
│   ├── Prometheus_Overview_uid3.json
│   └── Node_Metrics_uid4.json
├── Kubernetes/
│   └── Cluster_Status_uid5.json
└── manifest.txt                  # Summary of export
```

Each dashboard is:
- ✅ Organized by folder
- ✅ Named with title and UID
- ✅ Pure JSON (ready to import)
- ✅ Includes all panels and settings

---

## 🔧 Troubleshooting

### Python Version
Both scripts require **Python 3.6+**:
```bash
python3 --version
# Should show: Python 3.6.x or higher
```

### Script Not Executable
```bash
chmod +x export_grafana_dashboards.py
chmod +x check_grafana_pvc.py
```

### kubectl Not Found (check_grafana_pvc.py)
```bash
# Install kubectl first
# macOS: brew install kubectl
# Linux: Follow https://kubernetes.io/docs/tasks/tools/
```

### Connection Refused (export_grafana_dashboards.py)
```bash
# Make sure port-forward is running
kubectl port-forward -n infra svc/prometheus-grafana 3000:80

# Or check if Grafana is accessible directly
curl http://localhost:3000/api/health
```

### 401 Unauthorized
- API key is invalid or expired
- API key doesn't have Admin role
- Create a new API key in Grafana UI

### Can't Find Grafana Pod (check_grafana_pvc.py)
```bash
# Check if Grafana is running
kubectl get pods -n infra | grep grafana

# If in different namespace:
./check_grafana_pvc.py --namespace YOUR_NAMESPACE
```

---

## 💡 Pro Tips

### 1. Schedule Regular Backups
```bash
# Add to cron (daily at 2 AM)
0 2 * * * cd /backups && /path/to/export_grafana_dashboards.py
```

### 2. Store Backups in Git
```bash
./export_grafana_dashboards.py --output ./git-repo/grafana-backups
cd git-repo
git add grafana-backups
git commit -m "Backup dashboards $(date +%Y-%m-%d)"
git push
```

### 3. Compare Before Migration
```bash
# Export before migration
./export_grafana_dashboards.py --output ./before-migration

# After migration, export again
./export_grafana_dashboards.py --output ./after-migration

# Compare
diff -r before-migration/ after-migration/
```

### 4. Check PVC Before Making Decisions
```bash
# See actual usage
./check_grafana_pvc.py

# Decide: Keep PVC size or increase it?
# If < 50% used → can keep same size
# If > 75% used → increase in new deployment
```

---

## 🚀 Recommended Workflow

```bash
# 1. Check current PVC
./check_grafana_pvc.py > pvc-check.txt

# 2. Export dashboards
export GRAFANA_API_KEY="your-key"
./export_grafana_dashboards.py

# 3. Review the output
ls -lh grafana-dashboards-backup-*/

# 4. Store backup safely
tar -czf grafana-backup-$(date +%Y%m%d).tar.gz grafana-dashboards-backup-*/
# Upload to S3, store in Git, etc.

# 5. Proceed with migration
# (Now you have a safety net!)
```

---

## 📚 Help

Both scripts have built-in help:

```bash
./export_grafana_dashboards.py --help
./check_grafana_pvc.py --help
```

---

## ⚡ Quick Command Reference

```bash
# Check PVC
./check_grafana_pvc.py

# Export with defaults
export GRAFANA_API_KEY="key"
./export_grafana_dashboards.py

# Export with custom path
./export_grafana_dashboards.py --output /my/backup/path

# Export from remote
./export_grafana_dashboards.py --url https://grafana.example.com

# Check specific PVC
./check_grafana_pvc.py --namespace prod --pvc grafana-storage
```

That's it! Simple Python scripts, no dependencies, easy to use. 🎉
