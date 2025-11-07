# Import Dashboards to New Grafana - Quick Guide

## 🎯 Overview

Use **[import_grafana_dashboards.py](import_grafana_dashboards.py)** to load your exported dashboards into the new Grafana instance.

## 🚀 Basic Usage

```bash
# Port-forward to new Grafana
kubectl port-forward -n monitoring svc/kube-prom-stack-grafana 3000:80 &

# Create API key in new Grafana (or use create_api_key.py)
./create_api_key.py --url http://localhost:3000 --username admin

# Import dashboards
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_NEW_GRAFANA_API_KEY" \
  --input ./grafana-dashboards-backup-20241105-143022
```

## 📋 What It Does

The script will:
1. ✅ Connect to new Grafana
2. ✅ Scan input directory for dashboard JSON files
3. ✅ Automatically create folders if needed
4. ✅ Import each dashboard
5. ✅ Preserve folder organization
6. ✅ Update existing dashboards (by default)

## 📖 Examples

### Import to Original Folders
```bash
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./grafana-dashboards-backup-20241105
```

This recreates the folder structure from export:
- `General/` → General folder in Grafana
- `Monitoring/` → Monitoring folder in Grafana
- `Kubernetes/` → Kubernetes folder in Grafana

### Import All to Single Folder
```bash
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./grafana-dashboards-backup-20241105 \
  --folder "Imported Dashboards"
```

All dashboards go into "Imported Dashboards" folder (created automatically).

### Import Without Overwriting
```bash
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY" \
  --input ./grafana-dashboards-backup-20241105 \
  --no-overwrite
```

Skips dashboards that already exist (by UID).

### Import from Remote Grafana
```bash
./import_grafana_dashboards.py \
  --url https://grafana.wat.im \
  --api-key "YOUR_KEY" \
  --input ./backups
```

## 🔄 Complete Migration Workflow

### Step 1: Export from Old Grafana
```bash
# Port-forward to old
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &

# Create API key
./create_api_key.py --url http://localhost:3000 --username admin

# Export
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "OLD_KEY" \
  --output ./grafana-backup

# Kill port-forward
pkill -f "port-forward.*grafana"
```

### Step 2: Deploy New Grafana
```bash
# Deploy new stack
helm install kube-prom-stack \
  oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values kube-prometheus-stack-values-with-existing-pvc.yaml

# Wait for ready
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=grafana \
  -n monitoring \
  --timeout=300s
```

### Step 3: Import to New Grafana
```bash
# Port-forward to new
kubectl port-forward -n monitoring svc/kube-prom-stack-grafana 3000:80 &

# Create API key in new Grafana
./create_api_key.py --url http://localhost:3000 --username admin

# Import dashboards
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "NEW_KEY" \
  --input ./grafana-backup
```

### Step 4: Verify
```bash
# Open new Grafana
# Via ingress: https://grafana.wat.im
# Or port-forward: http://localhost:3000

# Login
# Username: admin
# Password: kubectl get secret kube-prom-stack-grafana -n monitoring \
#            -o jsonpath="{.data.admin-password}" | base64 -d

# Check:
# - All dashboards present
# - Correct folders
# - Datasources configured
# - Panels showing data
```

## 📊 Example Output

```
[INFO] Starting Grafana dashboard import...
[INFO] Grafana URL: http://localhost:3000
[INFO] Input directory: ./grafana-dashboards-backup-20241105
[INFO] Overwrite existing: True
[INFO] Testing connection to Grafana...
[INFO] ✓ Connected to Grafana (Org: Main Org.)

[INFO] Scanning for dashboard files...
[INFO] Found 15 dashboard file(s)

[INFO] Dashboards organized in 3 folder(s):
  - General: 5 dashboard(s)
  - Monitoring: 7 dashboard(s)
  - Kubernetes: 3 dashboard(s)

[INFO] [1/15] Importing: General/Overview_abc123.json
[INFO]   ✓ Imported successfully (UID: abc123)
[INFO] [2/15] Importing: General/Summary_def456.json
[INFO]   ✓ Imported successfully (UID: def456)
[INFO] [3/15] Importing: Monitoring/Prometheus_ghi789.json
[INFO]   ✓ Imported successfully (UID: ghi789)
...
[INFO] ==================================================
[INFO] Import Summary
[INFO] ==================================================
[INFO] Total files: 15
[INFO] Successfully imported: 15
[INFO] Input directory: ./grafana-dashboards-backup-20241105
[INFO] ==================================================
[INFO] Import complete! ✓
```

## 🎨 Features

### Automatic Folder Creation
- Creates folders automatically if they don't exist
- Preserves folder organization from export
- Can import all to a single folder with `--folder`

### UID Preservation
- Keeps dashboard UIDs from export
- Updates existing dashboards with same UID
- Allows seamless dashboard updates

### Error Handling
- Validates JSON before import
- Reports failures clearly
- Continues on errors
- Summary at end

### Flexible Options
- Overwrite or skip existing dashboards
- Import to original folders or single folder
- Works with any Grafana version

## 🆘 Troubleshooting

### Connection Refused
```
[ERROR] Failed to connect to Grafana
```

**Solution:**
```bash
# Check port-forward is running
ps aux | grep port-forward

# Restart if needed
pkill -f "port-forward.*grafana"
kubectl port-forward -n monitoring svc/kube-prom-stack-grafana 3000:80 &
```

### Invalid API Key
```
[ERROR] Invalid API key or insufficient permissions
```

**Solution:**
- Create new API key with Admin or Editor role
- Use `./create_api_key.py` to create it
- Or create manually in Grafana UI

### No Dashboards Found
```
[WARN] No dashboard JSON files found in ...
```

**Solution:**
- Check input directory path is correct
- Ensure directory contains .json files
- Check: `ls -lh ./grafana-dashboards-backup-*/`

### Dashboard Already Exists
```
[WARN] Dashboard already exists (skipped)
```

**Solution:**
- This is normal with `--no-overwrite`
- To update: remove `--no-overwrite` flag
- Or delete dashboard in Grafana UI first

### Folder Creation Failed
```
[WARN] Could not create folder 'FolderName': ...
```

**Solution:**
- Check API key has permissions
- Folder might have special characters
- Try `--folder` to import to single folder

## 💡 Pro Tips

### 1. Dry Run (Sort of)
```bash
# Import to test folder first
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "KEY" \
  --input ./backups \
  --folder "Test Import"

# Check in Grafana, then delete folder if good
```

### 2. Import Specific Folders
```bash
# Only import from Kubernetes folder
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "KEY" \
  --input ./grafana-dashboards-backup-20241105/Kubernetes
```

### 3. Update Dashboards Later
```bash
# Re-import to update existing dashboards
./import_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "KEY" \
  --input ./updated-dashboards
```

### 4. Combine with Export
```bash
# Export from prod, import to dev
./export_grafana_dashboards.py \
  --url https://grafana-prod.example.com \
  --api-key "PROD_KEY" \
  --output ./prod-export

./import_grafana_dashboards.py \
  --url https://grafana-dev.example.com \
  --api-key "DEV_KEY" \
  --input ./prod-export \
  --folder "From Production"
```

## ✅ Verification Checklist

After import:
- [ ] Check dashboard count matches export
- [ ] Verify folders are created
- [ ] Open a few dashboards
- [ ] Check panels show data
- [ ] Verify datasources are configured
- [ ] Test dashboard links work
- [ ] Check variables are set

## 📚 Related Scripts

- **export_grafana_dashboards.py** - Export dashboards from Grafana
- **create_api_key.py** - Create API keys programmatically
- **check_grafana_pvc.py** - Check PVC size and usage

## 🔐 Security Note

Delete API keys after use:
```bash
# List keys
./create_api_key.py --url http://localhost:3000 --username admin --list-only

# Delete in Grafana UI:
# Configuration → API Keys → trash icon
```

## 🎉 Success!

Your dashboards are now in the new Grafana instance! 🚀

```
Old Grafana (infra) → Export → Import → New Grafana (monitoring) ✓
```
