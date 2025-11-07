#!/usr/bin/env python3
"""
Export Grafana Dashboards
Exports all dashboards from a Grafana instance using the HTTP API.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


def print_info(msg):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def print_error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}", file=sys.stderr)


def print_warn(msg):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def print_step(msg):
    print(f"{Colors.BLUE}[STEP]{Colors.NC} {msg}")


def make_request(url, api_key, method='GET', data=None):
    """Make HTTP request to Grafana API"""
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    req = Request(url, headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode('utf-8')
    
    try:
        with urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        print_error(f"HTTP {e.code} error: {e.reason}")
        if e.code == 401:
            print_error("Invalid API key or insufficient permissions")
        return None
    except URLError as e:
        print_error(f"Connection error: {e.reason}")
        return None


def sanitize_filename(name):
    """Sanitize string for use as filename"""
    # Replace invalid characters with underscore
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name


def export_dashboards(grafana_url, api_key, output_dir):
    """Export all dashboards from Grafana"""
    
    # Remove trailing slash from URL
    grafana_url = grafana_url.rstrip('/')
    
    print_info("Starting Grafana dashboard export...")
    print_info(f"Grafana URL: {grafana_url}")
    print_info(f"Output directory: {output_dir}")
    
    # Test connection
    print_info("Testing connection to Grafana...")
    org_url = f"{grafana_url}/api/org"
    org_info = make_request(org_url, api_key)
    
    if not org_info:
        print_error("Failed to connect to Grafana")
        return False
    
    print_info(f"✓ Connected to Grafana (Org: {org_info.get('name', 'Unknown')})")
    
    # Get list of all dashboards
    print_info("Fetching list of dashboards...")
    search_url = f"{grafana_url}/api/search?type=dash-db"
    dashboards = make_request(search_url, api_key)
    
    if not dashboards:
        print_warn("No dashboards found or error occurred")
        return False
    
    if not isinstance(dashboards, list):
        print_error("Unexpected response format")
        return False
    
    dashboard_count = len(dashboards)
    print_info(f"Found {dashboard_count} dashboards to export")
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Export each dashboard
    exported = 0
    failed = 0
    
    for idx, dashboard in enumerate(dashboards, 1):
        uid = dashboard.get('uid')
        title = dashboard.get('title', 'Unknown')
        folder = dashboard.get('folderTitle', 'General')
        
        print_info(f"[{idx}/{dashboard_count}] Exporting: {folder}/{title} (UID: {uid})")
        
        # Create folder structure
        folder_path = output_path / sanitize_filename(folder)
        folder_path.mkdir(exist_ok=True)
        
        # Get dashboard details
        dashboard_url = f"{grafana_url}/api/dashboards/uid/{uid}"
        dashboard_data = make_request(dashboard_url, api_key)
        
        if not dashboard_data:
            print_error(f"  ✗ Failed to export")
            failed += 1
            continue
        
        # Extract just the dashboard JSON
        dashboard_json = dashboard_data.get('dashboard')
        if not dashboard_json:
            print_error(f"  ✗ No dashboard data in response")
            failed += 1
            continue
        
        # Save to file
        filename = sanitize_filename(title)
        output_file = folder_path / f"{filename}_{uid}.json"
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(dashboard_json, f, indent=2, ensure_ascii=False)
            print_info(f"  ✓ Exported to: {output_file}")
            exported += 1
        except IOError as e:
            print_error(f"  ✗ Failed to write file: {e}")
            failed += 1
    
    # Create manifest file
    manifest_file = output_path / "manifest.txt"
    try:
        with open(manifest_file, 'w') as f:
            f.write("Grafana Dashboard Export\n")
            f.write(f"Date: {datetime.now().isoformat()}\n")
            f.write(f"Grafana URL: {grafana_url}\n")
            f.write(f"Total Dashboards: {dashboard_count}\n")
            f.write(f"Successfully Exported: {exported}\n")
            f.write(f"Failed: {failed}\n")
            f.write("\nDashboard List:\n")
            
            # List all exported files
            for json_file in sorted(output_path.rglob("*.json")):
                f.write(f"{json_file}\n")
        
        print_info(f"Manifest file created: {manifest_file}")
    except IOError as e:
        print_warn(f"Failed to create manifest file: {e}")
    
    # Summary
    print()
    print_info("=" * 40)
    print_info("Export Summary")
    print_info("=" * 40)
    print_info(f"Total dashboards: {dashboard_count}")
    print_info(f"Successfully exported: {exported}")
    if failed > 0:
        print_warn(f"Failed: {failed}")
    print_info(f"Output directory: {output_dir}")
    print_info("=" * 40)
    
    return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description='Export Grafana dashboards via API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export from local Grafana
  %(prog)s --url http://localhost:3000 --api-key YOUR_API_KEY
  
  # Export to specific directory
  %(prog)s --url http://grafana.example.com --api-key YOUR_KEY --output ./backups
  
  # Export from remote Grafana with TLS
  %(prog)s --url https://grafana.wat.im --api-key YOUR_KEY

How to create an API key:
  1. Login to Grafana
  2. Click Configuration (⚙️) → API Keys
  3. Click "Add API key" button
  4. Fill in:
     - Key name: backup (or any name you prefer)
     - Role: Admin (required for full access)
     - Time to live: Leave default or set expiration
  5. Click "Add"
  6. Copy the key immediately (you won't see it again!)
  7. Use it with --api-key parameter
        """
    )
    
    parser.add_argument(
        '--url',
        required=True,
        help='Grafana URL (e.g., http://localhost:3000 or https://grafana.wat.im)'
    )
    
    parser.add_argument(
        '--api-key',
        required=True,
        help='Grafana API key with Admin role'
    )
    
    parser.add_argument(
        '--output',
        default=f'./grafana-dashboards-backup-{datetime.now().strftime("%Y%m%d-%H%M%S")}',
        help='Output directory (default: ./grafana-dashboards-backup-TIMESTAMP)'
    )
    
    args = parser.parse_args()
    
    # Export dashboards
    success = export_dashboards(args.url, args.api_key, args.output)
    
    if success:
        print_info("Backup complete! ✓")
        sys.exit(0)
    else:
        print_error("Backup completed with errors")
        sys.exit(1)


if __name__ == '__main__':
    main()
