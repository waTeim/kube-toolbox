# Python Scripts - Quick Usage Guide

## 📦 Scripts Provided

1. **export_grafana_dashboards.py** - Export all Grafana dashboards
2. **import_grafana_dashboards.py** - Import dashboards to Grafana
3. **create_api_key.py** - Create API keys programmatically
4. **check_grafana_pvc.py** - Check your current Grafana PVC size

All scripts are pure Python 3 with no external dependencies (uses only stdlib).

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

### Prerequisites

You need a Grafana API key.

**Option A: Automated (Easy!)** - Recommended if you can't find API Keys in UI
```bash
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &
./create_api_key.py --url http://localhost:3000 --username admin
# Copy the key it displays
```

**Option B: Manual via UI** - See [HOW_TO_GET_API_KEY.md](HOW_TO_GET_API_KEY.md)
1. Open http://localhost:3000
2. Configuration → API Keys → Add API Key
3. Name: backup, Role: Admin
4. Copy the key

### Basic Usage

```bash
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_API_KEY_HERE"
```

### Export from Local Grafana (Port-Forward)

```bash
# Start port-forward
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &

# Export dashboards
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "eyJrIjoiWXl6eFM3..."

# Kill port-forward when done
pkill -f "port-forward.*grafana"
```

### Export to Custom Directory

```bash
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --output /path/to/backup
```

### Export from Remote Grafana (via Ingress)

```bash
# If Grafana is accessible via ingress
./export_grafana_dashboards.py \
  --url https://grafana.wat.im \
  --api-key "YOUR_KEY"
```

### Read Key from File (Secure)

```bash
# Store key in file (one-time)
echo "YOUR_API_KEY" > ~/.grafana-api-key
chmod 600 ~/.grafana-api-key

# Use it
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "$(cat ~/.grafana-api-key)"

# Delete when done
rm ~/.grafana-api-key
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

## 📥 Import Dashboards to New Grafana

After you've deployed your new Grafana and exported your old dashboards, import them.

### Basic Import

```bash
# Port-forward to new Grafana
kubectl port-forward -n monitoring svc/kube-prom-stack-grafana 3000:80 &

# Create API key in new Grafana
./create_api_key.py --url http://localhost:3000 --username admin

# Import dashboards
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_NEW_KEY" \
  --input ./grafana-dashboards-backup-20241105
```

### Import Options

**Import to specific folder:**
```bash
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./backups \
  --folder "Imported Dashboards"
```

**Import without overwriting:**
```bash
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./backups \
  --no-overwrite
```

**See [IMPORT_DASHBOARDS_GUIDE.md](IMPORT_DASHBOARDS_GUIDE.md) for complete details.**

---

## 🔑 Create API Keys Programmatically

If you can't find API Keys in Grafana UI (older versions or Grafana 10+), create them programmatically.

### Basic Usage

```bash
# Port-forward to Grafana
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &

# Create API key (will prompt for password)
./create_api_key.py --url http://localhost:3000 --username admin

# Copy the key it displays
```

### With Password

```bash
# Get admin password
ADMIN_PASS=$(kubectl get secret prometheus-grafana -n infra \
  -o jsonpath="{.data.admin-password}" | base64 -d)

# Create key
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --password "$ADMIN_PASS"
```

### Custom Options

```bash
# Custom key name and expiration (30 days)
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --key-name my-backup \
  --ttl 2592000

# List existing keys
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --list-only
```

**See [SOLUTION_API_KEY.md](SOLUTION_API_KEY.md) for more details.**

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
# Store API key securely
echo "YOUR_API_KEY" > /root/.grafana-backup-key
chmod 600 /root/.grafana-backup-key

# Add to cron (daily at 2 AM)
# Edit: crontab -e
0 2 * * * cd /backups && /usr/local/bin/export_grafana_dashboards.py --url http://localhost:3000 --api-key "$(cat /root/.grafana-backup-key)" --output /backups/$(date +\%Y\%m\%d)
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

# 2. Port-forward to Grafana
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &

# 3. Create API key in Grafana UI (see HOW_TO_GET_API_KEY.md)

# 4. Export dashboards
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_API_KEY"

# 5. Review the output
ls -lh grafana-dashboards-backup-*/

# 6. Store backup safely
tar -czf grafana-backup-$(date +%Y%m%d).tar.gz grafana-dashboards-backup-*/
# Upload to S3, store in Git, etc.

# 7. Clean up
pkill -f "port-forward.*grafana"

# 8. Delete API key in Grafana UI

# 9. Proceed with migration
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

# Create API key
./create_api_key.py --url http://localhost:3000 --username admin

# Export dashboards
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY"

# Import dashboards
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./grafana-dashboards-backup-TIMESTAMP

# Export with custom path
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --output /my/backup/path

# Import to specific folder
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./backups \
  --folder "Imported"

# Export from remote
./export_grafana_dashboards.py \
  --url https://grafana.example.com \
  --api-key "YOUR_KEY"

# Import without overwrite
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./backups \
  --no-overwrite

# Check specific PVC
./check_grafana_pvc.py --namespace prod --pvc grafana-storage

# Get help
./export_grafana_dashboards.py --help
./import_grafana_dashboards.py --help
./create_api_key.py --help
./check_grafana_pvc.py --help
```

That's it! Simple Python scripts, no dependencies, easy to use. 🎉
