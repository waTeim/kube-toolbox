# How to Obtain a Grafana API Key

## 🚀 Method 1: Automated (Recommended for Older Grafana)

If you can't find the API Keys section in the UI (older Grafana versions or different UI layout), use this automated script:

```bash
# Port-forward to Grafana
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &

# Get your admin password
ADMIN_PASS=$(kubectl get secret prometheus-grafana -n infra \
  -o jsonpath="{.data.admin-password}" | base64 -d)
echo "Admin password: $ADMIN_PASS"

# Create API key automatically (will prompt for password)
./create_api_key.py --url http://localhost:3000 --username admin

# It will:
# 1. Check your Grafana version
# 2. List existing API keys
# 3. Create a new key named 'backup-export' with Admin role
# 4. Display the key for you to copy
```

**Output will look like:**
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
```

**Then use it:**
```bash
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "eyJrIjoiWXl6eFM3NmFkZjM0..."
```

---

## 🖱️ Method 2: Manual via UI (Newer Grafana)

## Quick Steps

1. **Access Grafana**
   ```bash
   # Port-forward to your current Grafana
   kubectl port-forward -n infra svc/prometheus-grafana 3000:80
   ```

2. **Login to Grafana**
   - Open browser: http://localhost:3000
   - Login with your credentials
   - Default username is usually: `admin`
   - Get password:
     ```bash
     kubectl get secret prometheus-grafana -n infra \
       -o jsonpath="{.data.admin-password}" | base64 -d; echo
     ```

3. **Navigate to API Keys**
   - Click the **Configuration** icon (⚙️) in the left sidebar
   - Click **API Keys**
   - Or go directly to: http://localhost:3000/org/apikeys

4. **Create New API Key**
   - Click the **"Add API key"** button (or "New API key")
   
   ![Add API Key Button](you'll see a blue button)

5. **Fill in the Form**
   ```
   Key name:       backup
   Role:           Admin       ← IMPORTANT: Must be Admin for export
   Time to live:   (leave empty for no expiration, or set to 30d)
   ```

6. **Add and Copy**
   - Click **"Add"** button
   - **CRITICAL**: Copy the API key immediately!
   - You will **NEVER** see this key again
   - It looks like: `eyJrIjoiWXl6eFM3NmF...` (long string)

7. **Save the Key**
   ```bash
   # Save to a file temporarily
   echo "eyJrIjoiWXl6eFM3NmF..." > ~/.grafana-api-key
   chmod 600 ~/.grafana-api-key
   
   # Or just keep it in your clipboard for immediate use
   ```

8. **Use the Key**
   ```bash
   # Export dashboards
   ./export_grafana_dashboards.py \
     --url http://localhost:3000 \
     --api-key "eyJrIjoiWXl6eFM3NmF..."
   
   # Or read from file
   ./export_grafana_dashboards.py \
     --url http://localhost:3000 \
     --api-key "$(cat ~/.grafana-api-key)"
   ```

9. **Delete the Key When Done** (Security Best Practice)
   - Go back to Configuration → API Keys
   - Find your "backup" key
   - Click the trash icon 🗑️
   - Confirm deletion

---

## Detailed Walkthrough with Screenshots

### Step 1: Access Configuration Menu

After logging in, look at the **left sidebar**:

```
┌─────────────────────┐
│                     │
│  🏠 Home           │
│  📊 Dashboards     │
│  🔍 Explore        │
│  ⚙️  Configuration │  ← Click here!
│  🔔 Alerting       │
│                     │
└─────────────────────┘
```

### Step 2: Click API Keys

The Configuration menu expands:

```
⚙️  Configuration
    ├─ Data Sources
    ├─ Users
    ├─ Teams
    ├─ Plugins
    ├─ Preferences
    ├─ API Keys         ← Click here!
    └─ ...
```

### Step 3: View API Keys Page

You'll see a page like:

```
API Keys                                    [+ Add API key]
───────────────────────────────────────────────────────────
Name        Role     Expires
───────────────────────────────────────────────────────────
(your existing keys, if any)
```

### Step 4: Fill in the Form

When you click "+ Add API key", a form appears:

```
┌─────────────────────────────────────────────┐
│  Add API Key                                │
├─────────────────────────────────────────────┤
│                                             │
│  Key name: [backup________________]         │
│                                             │
│  Role: [Admin ▼]  ← Must be Admin          │
│                                             │
│  Time to live: [_________________]          │
│                Optional                     │
│                                             │
│         [Cancel]  [Add]                     │
└─────────────────────────────────────────────┘
```

**Important**: Role MUST be **Admin** for the export script to work!

### Step 5: Copy the Generated Key

After clicking "Add", you'll see:

```
┌─────────────────────────────────────────────┐
│  API Key Created                            │
├─────────────────────────────────────────────┤
│                                             │
│  Your new API key:                          │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ eyJrIjoiWXl6eFM3NmFkZjM...         │   │
│  └─────────────────────────────────────┘   │
│                            [Copy] [📋]      │
│                                             │
│  ⚠️  Make sure to copy it now as you       │
│     won't be able to see it again!         │
│                                             │
│                    [Close]                  │
└─────────────────────────────────────────────┘
```

**Click the Copy button!** Don't just close the window!

---

## Troubleshooting

### Can't Find API Keys Menu

**Symptom**: No "API Keys" option in Configuration menu

**Cause**: User doesn't have permission

**Solution**: 
- Login as admin user
- Or ask an admin to create the key for you

### Role Options Don't Show "Admin"

**Symptom**: Dropdown only shows "Viewer" and "Editor"

**Cause**: Not logged in as an admin

**Solution**: Login with admin credentials

### Key Creation Fails

**Symptom**: Error when clicking "Add"

**Possible causes**:
1. Key name already exists → Use a different name
2. No permission → Need admin access
3. Organization setting → Check Grafana settings

### Lost the Key

**Symptom**: Closed the window without copying

**Solution**: You **cannot** recover it. You must:
1. Go back to API Keys page
2. Delete the key you just created
3. Create a new one
4. Copy it this time!

---

## Security Best Practices

### ✅ DO:
- Create key only when needed
- Delete key after use
- Use short expiration times (e.g., 1 day)
- Restrict key permissions to minimum needed
- Never commit keys to Git
- Never share keys via unencrypted channels

### ❌ DON'T:
- Leave keys active indefinitely
- Share keys between people
- Store keys in plain text in scripts
- Use the same key for everything
- Grant Admin role if Viewer/Editor is sufficient

---

## Alternative: Service Account Tokens (Grafana 9+)

If you're using Grafana 9.0+, you can use **Service Account Tokens** instead:

1. Go to Configuration → Service Accounts
2. Click "Add service account"
3. Name: `backup-service`
4. Role: Admin
5. Click "Create"
6. Click "Add service account token"
7. Copy the token

Service accounts are preferred over API keys in newer Grafana versions.

---

## Example: Complete Workflow

```bash
# 1. Port-forward to Grafana
kubectl port-forward -n infra svc/prometheus-grafana 3000:80 &
PF_PID=$!

# 2. Get admin password
ADMIN_PASS=$(kubectl get secret prometheus-grafana -n infra \
  -o jsonpath="{.data.admin-password}" | base64 -d)
echo "Admin password: $ADMIN_PASS"

# 3. Open Grafana
echo "Open: http://localhost:3000"
echo "Login as: admin / $ADMIN_PASS"

# 4. Create API key in UI (follow steps above)
# 5. Paste the key when prompted:
read -s -p "Enter API key: " API_KEY
echo

# 6. Export dashboards
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "$API_KEY"

# 7. Clean up
kill $PF_PID
unset API_KEY

# 8. Delete the API key in Grafana UI (Configuration → API Keys)

echo "Done! Dashboards exported."
```

---

## Quick Reference Card

```
┌──────────────────────────────────────────┐
│  GRAFANA API KEY CREATION                │
├──────────────────────────────────────────┤
│  1. Login to Grafana                     │
│  2. Configuration (⚙️) → API Keys        │
│  3. Click "+ Add API key"                │
│  4. Name: backup                         │
│  5. Role: Admin                          │
│  6. Click "Add"                          │
│  7. Copy key immediately!                │
│  8. Delete key after use                 │
└──────────────────────────────────────────┘
```

---

That's it! Now you can use the key with the export script:

```bash
./export_grafana_dashboards.py \
  --url http://localhost:3000 \
  --api-key "YOUR_KEY_HERE"
```
