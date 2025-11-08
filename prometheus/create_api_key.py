#!/usr/bin/env python3
"""
Create Grafana API Key / Service Account Token
Creates authentication using admin username/password
Automatically detects Grafana version and uses appropriate method:
  - Legacy API Keys for Grafana < 11
  - Service Accounts for Grafana >= 11
"""

import sys
import json
import argparse
import getpass
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from base64 import b64encode


class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'


def print_info(msg):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def print_error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}", file=sys.stderr)


def print_warn(msg):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def print_step(msg):
    print(f"{Colors.BLUE}[STEP]{Colors.NC} {msg}")


def make_request_with_auth(url, username, password, method='GET', data=None):
    """Make HTTP request with basic auth"""
    credentials = f"{username}:{password}"
    b64_credentials = b64encode(credentials.encode('utf-8')).decode('ascii')
    
    headers = {'Authorization': f'Basic {b64_credentials}', 'Content-Type': 'application/json'}
    
    req = Request(url, headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode('utf-8')
    
    try:
        with urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        return {'error': True, 'status_code': e.code, 'reason': e.reason, 'body': error_body}
    except URLError as e:
        return {'error': True, 'reason': str(e.reason)}


def parse_version(version_string):
    """Parse version string to tuple of integers"""
    try:
        parts = version_string.split('.')
        return tuple(int(p) for p in parts if p.isdigit())
    except:
        return (0, 0, 0)


def check_grafana_version(url, username, password):
    """Check Grafana version and health"""
    print_step("Checking Grafana version and health...")
    
    # Check health endpoint (no auth needed)
    health_url = f"{url}/api/health"
    try:
        req = Request(health_url)
        with urlopen(req) as response:
            health = json.loads(response.read().decode('utf-8'))
            print_info(f"✓ Grafana is healthy")
            if 'version' in health:
                version = health['version']
                print_info(f"✓ Grafana version: {version}")
                return version
    except Exception as e:
        print_warn(f"Could not check health endpoint: {e}")
    
    # Try to get version from API
    version_url = f"{url}/api/frontend/settings"
    result = make_request_with_auth(version_url, username, password)
    
    if not result.get('error'):
        version = result.get('buildInfo', {}).get('version', 'Unknown')
        print_info(f"✓ Grafana version: {version}")
        return version
    
    print_warn("Could not determine Grafana version")
    return "Unknown"


# ============================================================================
# LEGACY API KEYS (Grafana < 11)
# ============================================================================

def list_api_keys_legacy(url, username, password):
    """List existing API keys (legacy method)"""
    print_step("Checking existing API keys...")
    
    api_url = f"{url}/api/auth/keys"
    result = make_request_with_auth(api_url, username, password)
    
    if isinstance(result, dict) and result.get('error'):
        print_warn("Could not list API keys")
        return []
    
    if isinstance(result, list):
        return result
    
    return []


def create_api_key_legacy(url, username, password, key_name, role, seconds_to_live=None):
    """Create an API key (legacy method)"""
    print_step(f"Creating API key '{key_name}' with role '{role}'...")
    
    api_url = f"{url}/api/auth/keys"
    
    payload = {'name': key_name, 'role': role}
    
    if seconds_to_live:
        payload['secondsToLive'] = seconds_to_live
    
    result = make_request_with_auth(api_url, username, password, method='POST', data=payload)
    
    if result.get('error'):
        return None, result
    
    return result.get('key'), result


# ============================================================================
# SERVICE ACCOUNTS (Grafana >= 11)
# ============================================================================

def list_service_accounts(url, username, password):
    """List existing service accounts"""
    print_step("Checking existing service accounts...")
    
    api_url = f"{url}/api/serviceaccounts/search"
    result = make_request_with_auth(api_url, username, password)
    
    if isinstance(result, dict) and result.get('error'):
        print_warn("Could not list service accounts")
        return []
    
    if isinstance(result, dict) and 'serviceAccounts' in result:
        return result['serviceAccounts']
    
    return []


def create_service_account(url, username, password, account_name, role):
    """Create a service account"""
    print_step(f"Creating service account '{account_name}' with role '{role}'...")
    
    api_url = f"{url}/api/serviceaccounts"
    
    payload = {'name': account_name, 'role': role, 'isDisabled': False}
    
    result = make_request_with_auth(api_url, username, password, method='POST', data=payload)
    
    if result.get('error'):
        return None, result
    
    return result, None


def create_service_account_token(url, username, password, account_id, token_name, seconds_to_live=None):
    """Create a token for a service account"""
    print_step(f"Creating token '{token_name}' for service account...")
    
    api_url = f"{url}/api/serviceaccounts/{account_id}/tokens"
    
    payload = {'name': token_name}
    
    if seconds_to_live:
        payload['secondsToLive'] = seconds_to_live
    
    result = make_request_with_auth(api_url, username, password, method='POST', data=payload)
    
    if result.get('error'):
        return None, result
    
    return result.get('key'), result


def delete_service_account(url, username, password, account_id):
    """Delete a service account"""
    api_url = f"{url}/api/serviceaccounts/{account_id}"
    result = make_request_with_auth(api_url, username, password, method='DELETE')
    return result


# ============================================================================
# UNIFIED INTERFACE
# ============================================================================

def create_credentials_modern(url, username, password, name, role, ttl):
    """Create credentials using Service Accounts (Grafana >= 11)"""
    
    # List existing service accounts
    existing_accounts = list_service_accounts(url, username, password)
    if existing_accounts:
        print_info(f"Found {len(existing_accounts)} existing service account(s):")
        for account in existing_accounts:
            print(f"  - {account.get('name')} (Role: {account.get('role')}, ID: {account.get('id')})")
        print()
    else:
        print_info("No existing service accounts found")
        print()
    
    # Check if account with same name exists
    existing_account = next((a for a in existing_accounts if a.get('name') == name), None)
    if existing_account:
        print_warn(f"⚠️  Service account '{name}' already exists (ID: {existing_account.get('id')})")
        print_warn("You can either:")
        print_warn("  1. Use --name to create with a different name")
        print_warn("  2. Delete the existing account in Grafana UI first")
        print_warn("  3. Create a new token for the existing account manually in Grafana UI")
        return None, None
    
    # Create service account
    ttl_str = f"{ttl} seconds" if ttl else "No expiration"
    print_info(f"Creating service account with:")
    print_info(f"  Name: {name}")
    print_info(f"  Role: {role}")
    print_info(f"  Token TTL: {ttl_str}")
    print()
    
    account_result, error = create_service_account(url, username, password, name, role)
    
    if error:
        return None, error
    
    account_id = account_result.get('id')
    print_info(f"✓ Service account created (ID: {account_id})")
    print()
    
    # Create token for the service account
    token_name = f"{name}-token"
    token, token_error = create_service_account_token(url, username, password, account_id, token_name, ttl)
    
    if token:
        return token, None
    else:
        # Clean up the service account we just created
        print_warn("Cleaning up service account...")
        delete_service_account(url, username, password, account_id)
        return None, token_error


def create_credentials_legacy(url, username, password, name, role, ttl):
    """Create credentials using API Keys (Grafana < 11)"""
    
    # List existing API keys
    existing_keys = list_api_keys_legacy(url, username, password)
    if existing_keys:
        print_info(f"Found {len(existing_keys)} existing API key(s):")
        for key in existing_keys:
            expiration = key.get('expiration', 'Never')
            print(f"  - {key.get('name')} (Role: {key.get('role')}, Expires: {expiration})")
        print()
    else:
        print_info("No existing API keys found")
        print()
    
    # Check if key with same name exists
    key_exists = any(k.get('name') == name for k in existing_keys)
    if key_exists:
        print_warn(f"⚠️  API key '{name}' already exists")
        print_warn("You can either:")
        print_warn("  1. Use --name to create with a different name")
        print_warn("  2. Delete the existing key in Grafana UI first")
        print_warn("  3. Use the existing key if you have it saved")
        return None, None
    
    # Create API key
    ttl_str = f"{ttl} seconds" if ttl else "No expiration"
    print_info(f"Creating API key with:")
    print_info(f"  Name: {name}")
    print_info(f"  Role: {role}")
    print_info(f"  TTL: {ttl_str}")
    print()
    
    api_key, result = create_api_key_legacy(url, username, password, name, role, ttl)
    
    if api_key:
        return api_key, None
    else:
        return None, result


def main():
    parser = argparse.ArgumentParser(
        description='Create Grafana API credentials using admin username/password',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive (prompts for password)
  %(prog)s --url http://localhost:3000 --username admin
  
  # With all parameters
  %(prog)s --url http://localhost:3000 --username admin --password YOUR_PASSWORD
  
  # Custom name and role
  %(prog)s --url http://localhost:3000 --username admin --name my-backup --role Viewer
  
  # With expiration (30 days)
  %(prog)s --url http://localhost:3000 --username admin --ttl 2592000

Notes:
  - --url is required (Grafana URL)
  - Default username is 'admin'
  - Default name is 'backup-export'
  - Default role is 'Admin' (required for exporting dashboards)
  - Password will be prompted if not provided
  - Automatically detects version and uses:
    * Service Accounts for Grafana >= 11
    * Legacy API Keys for Grafana < 11
  - Get password with:
    kubectl get secret prometheus-grafana -n infra -o jsonpath="{.data.admin-password}" | base64 -d
        """
    )
    
    parser.add_argument('--url', required=True, help='Grafana URL (e.g., http://localhost:3000)')
    parser.add_argument('--username', default='admin', help='Grafana admin username (default: admin)')
    parser.add_argument('--password', help='Grafana admin password (will prompt if not provided)')
    parser.add_argument('--name', default='backup-export', help='Name for the credential (default: backup-export)')
    parser.add_argument('--role', default='Admin', choices=['Admin', 'Editor', 'Viewer'], help='Role for the credential (default: Admin)')
    parser.add_argument('--ttl', type=int, help='Time to live in seconds (e.g., 86400 for 1 day, 2592000 for 30 days)')
    parser.add_argument('--list-only', action='store_true', help='Only list existing credentials, don\'t create new ones')
    
    args = parser.parse_args()
    
    # Get password if not provided
    password = args.password
    if not password:
        password = getpass.getpass(f"Enter password for user '{args.username}': ")
    
    # Remove trailing slash from URL
    url = args.url.rstrip('/')
    
    print_info("=" * 50)
    print_info("Grafana API Credential Creator")
    print_info("=" * 50)
    print_info(f"URL: {url}")
    print_info(f"Username: {args.username}")
    print()
    
    # Check version and determine method
    version_str = check_grafana_version(url, args.username, password)
    version_tuple = parse_version(version_str)
    use_service_accounts = version_tuple >= (11, 0, 0)
    
    print()
    if use_service_accounts:
        print_info("Using Service Accounts method (Grafana 11+)")
    else:
        print_info("Using Legacy API Keys method (Grafana < 11)")
    print()
    
    # List only mode
    if args.list_only:
        if use_service_accounts:
            list_service_accounts(url, args.username, password)
        else:
            list_api_keys_legacy(url, args.username, password)
        sys.exit(0)
    
    # Create credentials using appropriate method
    if use_service_accounts:
        credential, error = create_credentials_modern(url, args.username, password, args.name, args.role, args.ttl)
    else:
        credential, error = create_credentials_legacy(url, args.username, password, args.name, args.role, args.ttl)
    
    # Handle success
    if credential:
        print()
        print_info("=" * 50)
        print_info("✓ Credential Created Successfully!")
        print_info("=" * 50)
        print()
        print_info("Your API Token:")
        print()
        print(f"  {credential}")
        print()
        print_warn("⚠️  IMPORTANT: Copy this token now!")
        print_warn("You won't be able to see it again.")
        print()
        print_info("Usage:")
        print()
        print(f"  ./export_grafana_dashboards.py \\")
        print(f"    --url {url} \\")
        print(f"    --api-key \"{credential}\"")
        print()
        print_info("Or save to file:")
        print()
        print(f"  echo \"{credential}\" > ~/.grafana-api-key")
        print(f"  chmod 600 ~/.grafana-api-key")
        print()
        print_info("=" * 50)
        sys.exit(0)
    
    # Handle errors
    if error is None:
        # This means duplicate name, already printed warning
        sys.exit(1)
    
    print()
    print_error("=" * 50)
    print_error("Failed to create credential")
    print_error("=" * 50)
    print()
    
    if error.get('status_code') == 401:
        print_error("Authentication failed!")
        print_error("Please check:")
        print_error("  - Username is correct (default: admin)")
        print_error("  - Password is correct")
        print_error("")
        print_error("Get password with:")
        print_error("  kubectl get secret prometheus-grafana -n infra \\")
        print_error("    -o jsonpath=\"{.data.admin-password}\" | base64 -d")
    
    elif error.get('status_code') == 403:
        print_error("Permission denied!")
        print_error(f"User '{args.username}' does not have permission to create credentials")
        print_error("You need to be an Admin")
    
    elif error.get('status_code') == 409:
        print_error("Credential with this name already exists")
        print_error("Use --name to specify a different name")
    
    else:
        print_error(f"HTTP {error.get('status_code')}: {error.get('reason')}")
        if error.get('body'):
            print_error(f"Details: {error.get('body')}")
    
    sys.exit(1)


if __name__ == '__main__':
    main()