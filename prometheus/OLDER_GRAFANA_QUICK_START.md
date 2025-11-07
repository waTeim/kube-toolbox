# Quick Start for Older Grafana Versions

Your Grafana version appears to be older and doesn't have the API Keys section in the same location. No problem!

## 🎯 Solution: Use the Automated Script

I've created a script that creates API keys programmatically using your admin username/password.

### Step 1: Get Your Admin Password

```bash
kubectl get secret prometheus-grafana -n infra \
  -o jsonpath="{.data.admin-password}" | base64 -d
```

Save this password - you'll need it in a moment.

### Step 2: Port-Forward to Grafana

```bash
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &
```

### Step 3: Create API Key Automatically

```bash
./create_api_key.py --url http://localhost:3000 --username admin
```

When prompted, enter the admin password from Step 1.

**The script will:**
- ✅ Check your Grafana version
- ✅ List any existing API keys
- ✅ Create a new API key named "backup-export"
- ✅ Display the key for you to copy

### Step 4: Copy the API Key

The output will look like:
```
[INFO] Your API Key:

  eyJrIjoiWXl6eFM3NmFkZjM0NTY3OGFiY2RlZjEyMzQ1Njc4OTA...

[WARN] ⚠️  IMPORTANT: Copy this key now!
```

Copy that long string starting with `eyJr...`

### Step 5: Check Your PVC Size

```bash
./check_grafana_pvc.py
```

This shows your current Grafana storage size and usage.

### Step 6: Export Your Dashboards

```bash
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "eyJrIjoiWXl6eFM3NmFkZjM0..."
```

Replace `eyJrIjoiWXl6eFM3NmFkZjM0...` with the actual key from Step 4.

### Step 7: You're Done!

Your dashboards are now backed up to:
```
./grafana-dashboards-backup-YYYYMMDD-HHMMSS/
```

---

## 🔧 Script Options

### Custom Key Name
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --key-name my-custom-backup
```

### With Expiration (30 days)
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --ttl 2592000
```

### Just List Existing Keys
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --list-only
```

### Non-Interactive (Provide Password)
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --password "YOUR_PASSWORD"
```

---

## 💡 Pro Tip: One-Liner

```bash
# Get password, create key, export dashboards - all in one go
ADMIN_PASS=$(kubectl get secret prometheus-grafana -n infra -o jsonpath="{.data.admin-password}" | base64 -d) && \
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &>/dev/null & \
PF_PID=$! && \
sleep 2 && \
API_KEY=$(./create_api_key.py --url http://localhost:3000 --username admin --password "$ADMIN_PASS" 2>/dev/null | grep -A1 "Your API Key:" | tail -1 | xargs) && \
./export_grafana_dashboards.py --url http://localhost:3000 --api-key "$API_KEY" && \
kill $PF_PID && \
echo "✓ Done! Dashboards exported."
```

---

## 🆘 Troubleshooting

### Authentication Failed
```
[ERROR] Authentication failed!
```

**Solution:**
- Double-check the admin password
- Make sure you're using username: `admin`
- Try getting password again: 
  ```bash
  kubectl get secret prometheus-grafana -n infra \
    -o jsonpath="{.data.admin-password}" | base64 -d
  ```

### Connection Refused
```
URLError: Connection refused
```

**Solution:**
- Make sure port-forward is running
- Check: `ps aux | grep port-forward`
- Restart it: 
  ```bash
  pkill -f "port-forward.*grafana"
  kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &
  ```

### Key Already Exists
```
[WARN] API key 'backup-export' already exists
```

**Solution:**
- Use a different name: `--key-name backup-export-2`
- Or list existing keys: `--list-only`
- Or if you have the original key saved, just use that

### Permission Denied
```
[ERROR] User 'admin' does not have permission
```

**Solution:**
- Make sure you're using the actual admin account
- Check if there are other admin users:
  ```bash
  kubectl exec -n infra deployment/prometheus-grafana -- \
    grafana-cli admin list-users
  ```

---

## 📚 What's Your Grafana Version?

The automated script tells you! Look for:
```
[INFO] ✓ Grafana version: 6.7.4
```

Common UI locations by version:
- **Grafana 6.x and earlier**: Configuration may be under different menu
- **Grafana 7.x-8.x**: Configuration → API Keys
- **Grafana 9.x+**: Configuration → API Keys (or Service Accounts)

Regardless of version, the automated script works! 🎉

---

## 🎯 Next Steps

After exporting your dashboards:

1. **Check PVC size**: `./check_grafana_pvc.py`
2. **Review exports**: `ls -lh grafana-dashboards-backup-*/`
3. **Proceed with migration**: See `YOUR_SPECIFIC_MIGRATION.md`

You're all set! The automated approach works for any Grafana version. 🚀
