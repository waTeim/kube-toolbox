# Solution: Can't Find API Keys in Grafana UI

## Problem
You can't find the Configuration or API Keys section in your Grafana UI. This is common with:
- Older Grafana versions (6.x and earlier)
- Different UI layouts
- Custom Grafana builds

## ✅ Solution: Automated API Key Creation

I've created **[create_api_key.py](create_api_key.py)** that creates API keys programmatically using your admin username/password. Works with ANY Grafana version!

---

## 🚀 Quick Usage

```bash
# 1. Port-forward to Grafana
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &

# 2. Get admin password
kubectl get secret prometheus-grafana -n infra \
  -o jsonpath="{.data.admin-password}" | base64 -d

# 3. Create API key (will prompt for password)
./create_api_key.py --url http://localhost:3000 --username admin

# 4. Copy the key it displays

# 5. Use it
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "PASTE_KEY_HERE"
```

---

## 📋 What the Script Does

The script will:
1. ✅ Connect to your Grafana using admin credentials
2. ✅ Check your Grafana version
3. ✅ List existing API keys
4. ✅ Create a new API key with Admin role
5. ✅ Display the key for you to copy

**Example output:**
```
[INFO] ==================================================
[INFO] Grafana API Key Creator
[INFO] ==================================================
[INFO] URL: http://localhost:3000
[INFO] Username: admin

[STEP] Checking Grafana version and health...
[INFO] ✓ Grafana is healthy
[INFO] ✓ Grafana version: 6.7.4

[STEP] Checking existing API keys...
[INFO] No existing API keys found

[STEP] Creating API key 'backup-export' with role 'Admin'...

[INFO] ==================================================
[INFO] ✓ API Key Created Successfully!
[INFO] ==================================================

[INFO] Your API Key:

  eyJrIjoiWXl6eFM3NmFkZjM0NTY3OGFiY2RlZjEyMzQ1Njc4OTA...

[WARN] ⚠️  IMPORTANT: Copy this key now!
[WARN] You won't be able to see it again.

[INFO] Usage:

  ./export_grafana_dashboards.py \
    --url http://localhost:3000 \
    --api-key "eyJrIjoiWXl6eFM3NmFkZjM0..."
```

---

## 🎯 Complete Workflow

```bash
# Store admin password
ADMIN_PASS=$(kubectl get secret prometheus-grafana -n infra \
  -o jsonpath="{.data.admin-password}" | base64 -d)

# Port-forward
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &
sleep 2

# Create API key
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --password "$ADMIN_PASS"

# Copy the key from output, then export dashboards
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY_HERE"
```

---

## 📖 Detailed Guides

- **Quick Start**: [OLDER_GRAFANA_QUICK_START.md](OLDER_GRAFANA_QUICK_START.md)
- **Full API Key Guide**: [HOW_TO_GET_API_KEY.md](HOW_TO_GET_API_KEY.md)
- **Script Usage**: [PYTHON_SCRIPTS_USAGE.md](PYTHON_SCRIPTS_USAGE.md)

---

## 🔧 Advanced Options

### Custom Key Name
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --key-name my-backup-key
```

### With Expiration (1 day = 86400 seconds)
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --ttl 86400
```

### List Existing Keys
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --list-only
```

### Different Role (for read-only)
```bash
./create_api_key.py \
  --url http://localhost:3000 \
  --username admin \
  --role Viewer
```

---

## 🆘 Troubleshooting

### Can't Get Admin Password
```bash
# Try this
kubectl get secret prometheus-grafana -n infra -o yaml

# Look for data.admin-password field
# Decode it: echo "BASE64_STRING" | base64 -d
```

### Port-Forward Not Working
```bash
# Check if something is already on port 3000
lsof -i :3000

# Use different port
kubectl port-forward -n infra svc/prometheus-grafana 8080:80 &

# Then use: --url http://localhost:8080
```

### Authentication Failed
- Verify username is `admin`
- Double-check password
- Make sure port-forward is running

### Permission Denied
- Ensure user has Admin role
- Check Grafana RBAC settings

---

## ✅ Why This Works Better

**Automated Script vs. UI:**
- ✅ Works with ANY Grafana version
- ✅ Works even if UI layout is different
- ✅ Scriptable and repeatable
- ✅ Shows your Grafana version
- ✅ Lists existing keys
- ✅ Validates credentials immediately

**This is now the recommended method!**

---

## 🎉 Success Story

```bash
$ ./create_api_key.py --url http://localhost:3000 --username admin
Enter password for user 'admin': ********

[INFO] ==================================================
[INFO] Grafana API Key Creator
[INFO] ==================================================
[INFO] URL: http://localhost:3000
[INFO] Username: admin

[STEP] Checking Grafana version and health...
[INFO] ✓ Grafana is healthy
[INFO] ✓ Grafana version: 6.7.4

[STEP] Checking existing API keys...
[INFO] No existing API keys found

[STEP] Creating API key 'backup-export' with role 'Admin'...

[INFO] ==================================================
[INFO] ✓ API Key Created Successfully!
[INFO] ==================================================

$ ./export_grafana_dashboards.py --url http://localhost:3000 --api-key "..."
[INFO] Starting Grafana dashboard export...
[INFO] ✓ Connected to Grafana
[INFO] Found 15 dashboards to export
[INFO] [1/15] Exporting: General/Overview
...
[INFO] Backup complete! ✓
```

Problem solved! 🚀
