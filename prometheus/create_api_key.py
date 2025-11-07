#!/usr/bin/env python3
"""
Create Grafana API Key
Creates an API key using admin username/password (no existing API key needed)
"""

import sys
import json
import argparse
import getpass
from urllib.request import Request, urlopen, HTTPPasswordMgrWithDefaultRealm, HTTPBasicAuthHandler, build_opener
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
    # Create auth header
    credentials = f"{username}:{password}"
    b64_credentials = b64encode(credentials.encode('utf-8')).decode('ascii')
    
    headers = {
        'Authorization': f'Basic {b64_credentials}',
        'Content-Type': 'application/json'
    }
    
    req = Request(url, headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode('utf-8')
    
    try:
        with urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        return {
            'error': True,
            'status_code': e.code,
            'reason': e.reason,
            'body': error_body
        }
    except URLError as e:
        return {
            'error': True,
            'reason': str(e.reason)
        }


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
                print_info(f"✓ Grafana version: {health['version']}")
                return health['version']
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


def create_api_key(url, username, password, key_name, role, seconds_to_live=None):
    """Create an API key"""
    print_step(f"Creating API key '{key_name}' with role '{role}'...")
    
    api_url = f"{url}/api/auth/keys"
    
    payload = {
        "name": key_name,
        "role": role
    }
    
    if seconds_to_live:
        payload["secondsToLive"] = seconds_to_live
    
    result = make_request_with_auth(api_url, username, password, method='POST', data=payload)
    
    if result.get('error'):
        return None, result
    
    return result.get('key'), result


def list_api_keys(url, username, password):
    """List existing API keys"""
    print_step("Checking existing API keys...")
    
    api_url = f"{url}/api/auth/keys"
    result = make_request_with_auth(api_url, username, password)
    
    # Check if it's an error dict
    if isinstance(result, dict) and result.get('error'):
        print_warn("Could not list API keys")
        return []
    
    # If it's a list, return it
    if isinstance(result, list):
        return result
    
    # Otherwise return empty list
    return []


def main():
    parser = argparse.ArgumentParser(
        description='Create Grafana API Key using admin credentials',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive (prompts for password)
  %(prog)s --url http://localhost:3000 --username admin
  
  # With all parameters
  %(prog)s --url http://localhost:3000 --username admin --password YOUR_PASSWORD
  
  # Custom key name and role
  %(prog)s --url http://localhost:3000 --username admin --key-name my-backup --role Viewer
  
  # With expiration (30 days)
  %(prog)s --url http://localhost:3000 --username admin --ttl 2592000

Notes:
  - --url is required (Grafana URL)
  - Default username is 'admin'
  - Default key name is 'backup-export'
  - Default role is 'Admin' (required for exporting dashboards)
  - Password will be prompted if not provided
  - Get password with:
    kubectl get secret prometheus-grafana -n infra -o jsonpath="{.data.admin-password}" | base64 -d
        """
    )
    
    parser.add_argument(
        '--url',
        required=True,
        help='Grafana URL (e.g., http://localhost:3000)'
    )
    
    parser.add_argument(
        '--username',
        default='admin',
        help='Grafana admin username (default: admin)'
    )
    
    parser.add_argument(
        '--password',
        help='Grafana admin password (will prompt if not provided)'
    )
    
    parser.add_argument(
        '--key-name',
        default='backup-export',
        help='Name for the API key (default: backup-export)'
    )
    
    parser.add_argument(
        '--role',
        default='Admin',
        choices=['Admin', 'Editor', 'Viewer'],
        help='Role for the API key (default: Admin)'
    )
    
    parser.add_argument(
        '--ttl',
        type=int,
        help='Time to live in seconds (e.g., 86400 for 1 day, 2592000 for 30 days)'
    )
    
    parser.add_argument(
        '--list-only',
        action='store_true',
        help='Only list existing API keys, don\'t create a new one'
    )
    
    args = parser.parse_args()
    
    # Get password if not provided
    password = args.password
    if not password:
        password = getpass.getpass(f"Enter password for user '{args.username}': ")
    
    # Remove trailing slash from URL
    url = args.url.rstrip('/')
    
    print_info("=" * 50)
    print_info("Grafana API Key Creator")
    print_info("=" * 50)
    print_info(f"URL: {url}")
    print_info(f"Username: {args.username}")
    print()
    
    # Check version
    version = check_grafana_version(url, args.username, password)
    print()
    
    # List existing keys
    existing_keys = list_api_keys(url, args.username, password)
    if existing_keys:
        print_info(f"Found {len(existing_keys)} existing API key(s):")
        for key in existing_keys:
            expiration = key.get('expiration', 'Never')
            print(f"  - {key.get('name')} (Role: {key.get('role')}, Expires: {expiration})")
        print()
    else:
        print_info("No existing API keys found")
        print()
    
    # Note for Grafana 9+
    version_parts = version.split('.')
    if version_parts[0].isdigit() and int(version_parts[0]) >= 9:
        print_info("Note: Grafana 9+ also supports Service Accounts")
        print_info("This script uses the traditional API Keys method which still works")
        print()
    
    # Exit if list-only
    if args.list_only:
        sys.exit(0)
    
    # Check if key with same name exists
    key_exists = any(k.get('name') == args.key_name for k in existing_keys)
    if key_exists:
        print_warn(f"⚠️  API key '{args.key_name}' already exists")
        print_warn("You can either:")
        print_warn("  1. Use --key-name to create with a different name")
        print_warn("  2. Delete the existing key in Grafana UI first")
        print_warn("  3. Use the existing key if you have it saved")
        sys.exit(1)
    
    # Create API key
    ttl_str = f"{args.ttl} seconds" if args.ttl else "No expiration"
    print_info(f"Creating API key with:")
    print_info(f"  Name: {args.key_name}")
    print_info(f"  Role: {args.role}")
    print_info(f"  TTL: {ttl_str}")
    print()
    
    api_key, result = create_api_key(
        url,
        args.username,
        password,
        args.key_name,
        args.role,
        args.ttl
    )
    
    if api_key:
        print()
        print_info("=" * 50)
        print_info("✓ API Key Created Successfully!")
        print_info("=" * 50)
        print()
        print_info("Your API Key:")
        print()
        print(f"  {api_key}")
        print()
        print_warn("⚠️  IMPORTANT: Copy this key now!")
        print_warn("You won't be able to see it again.")
        print()
        print_info("Usage:")
        print()
        print(f"  ./export_grafana_dashboards.py \\")
        print(f"    --url {url} \\")
        print(f"    --api-key \"{api_key}\"")
        print()
        print_info("Or save to file:")
        print()
        print(f"  echo \"{api_key}\" > ~/.grafana-api-key")
        print(f"  chmod 600 ~/.grafana-api-key")
        print()
        print_info("=" * 50)
        sys.exit(0)
    else:
        print()
        print_error("=" * 50)
        print_error("Failed to create API key")
        print_error("=" * 50)
        print()
        
        if result.get('status_code') == 401:
            print_error("Authentication failed!")
            print_error("Please check:")
            print_error("  - Username is correct (default: admin)")
            print_error("  - Password is correct")
            print_error("")
            print_error("Get password with:")
            print_error("  kubectl get secret prometheus-grafana -n infra \\")
            print_error("    -o jsonpath=\"{.data.admin-password}\" | base64 -d")
        
        elif result.get('status_code') == 403:
            print_error("Permission denied!")
            print_error(f"User '{args.username}' does not have permission to create API keys")
            print_error("You need to be an Admin to create API keys")
        
        elif result.get('status_code') == 409:
            print_error("API key with this name already exists")
            print_error("Use --key-name to specify a different name")
        
        else:
            print_error(f"HTTP {result.get('status_code')}: {result.get('reason')}")
            if result.get('body'):
                print_error(f"Details: {result.get('body')}")
        
        sys.exit(1)


if __name__ == '__main__':
    main()
