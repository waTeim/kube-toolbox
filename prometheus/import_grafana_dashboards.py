#!/usr/bin/env python3
"""
Import Grafana Dashboards
Imports dashboards from JSON files to a Grafana instance using the HTTP API.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color


def print_info(msg):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def print_error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}", file=sys.stderr)


def print_warn(msg):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def print_step(msg):
    print(f"{Colors.BLUE}[STEP]{Colors.NC} {msg}")


def print_dry_run(msg):
    print(f"{Colors.CYAN}[DRY-RUN]{Colors.NC} {msg}")


def make_request(url, api_key, method='GET', data=None):
    """Make HTTP request to Grafana API"""
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    
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


def get_or_create_folder(grafana_url, api_key, folder_title, dry_run=False):
    """Get folder ID by title, or create if it doesn't exist"""
    
    # Check if folder exists
    folders_url = f"{grafana_url}/api/folders"
    folders = make_request(folders_url, api_key)
    
    if isinstance(folders, list):
        for folder in folders:
            if folder.get('title') == folder_title:
                return folder.get('id')
    
    # Folder doesn't exist, create it (or simulate in dry-run)
    if dry_run:
        print_dry_run(f"Would create folder '{folder_title}'")
        return -1  # Return dummy ID for dry-run
    
    create_data = {'title': folder_title}
    result = make_request(folders_url, api_key, method='POST', data=create_data)
    
    if result.get('error'):
        print_warn(f"Could not create folder '{folder_title}': {result.get('reason', 'Unknown error')}")
        return None
    
    return result.get('id')


def import_dashboard(grafana_url, api_key, dashboard_json, folder_id=None, overwrite=True, dry_run=False):
    """Import a dashboard to Grafana"""
    
    # Prepare import payload
    payload = {'dashboard': dashboard_json, 'overwrite': overwrite, 'inputs': []}
    
    if folder_id is not None:
        payload['folderId'] = folder_id
    
    # In dry-run mode, just return success without making the request
    if dry_run:
        dashboard_title = dashboard_json.get('title', 'Unknown')
        dashboard_uid = dashboard_json.get('uid', 'new')
        return {'status': 'success', 'uid': dashboard_uid, 'url': f'/d/{dashboard_uid}', 'title': dashboard_title, 'dry_run': True}
    
    # Import dashboard
    import_url = f"{grafana_url}/api/dashboards/db"
    result = make_request(import_url, api_key, method='POST', data=payload)
    
    return result


def find_dashboard_files(input_dir):
    """Find all JSON files in the input directory"""
    dashboard_files = []
    input_path = Path(input_dir)
    
    if not input_path.exists():
        return []
    
    # Find all .json files recursively
    for json_file in input_path.rglob('*.json'):
        # Skip manifest.txt and other non-dashboard files
        if json_file.name == 'manifest.txt':
            continue
        
        # Get folder name (parent directory name)
        folder_name = json_file.parent.name
        if folder_name == input_path.name:
            folder_name = 'General'
        
        dashboard_files.append({'path': json_file, 'folder': folder_name, 'filename': json_file.name})
    
    return dashboard_files


def import_dashboards(grafana_url, api_key, input_dir, target_folder=None, overwrite=True, dry_run=False):
    """Import all dashboards from directory"""
    
    # Remove trailing slash from URL
    grafana_url = grafana_url.rstrip('/')
    
    if dry_run:
        print_dry_run("=" * 60)
        print_dry_run("DRY-RUN MODE: No changes will be made to Grafana")
        print_dry_run("=" * 60)
        print()
    
    print_info("Starting Grafana dashboard import...")
    print_info(f"Grafana URL: {grafana_url}")
    print_info(f"Input directory: {input_dir}")
    print_info(f"Overwrite existing: {overwrite}")
    print_info(f"Dry-run mode: {dry_run}")
    
    # Test connection
    print_info("Testing connection to Grafana...")
    org_url = f"{grafana_url}/api/org"
    org_info = make_request(org_url, api_key)
    
    if org_info.get('error'):
        print_error("Failed to connect to Grafana")
        if org_info.get('status_code') == 401:
            print_error("Invalid API key or insufficient permissions")
        return False
    
    print_info(f"✓ Connected to Grafana (Org: {org_info.get('name', 'Unknown')})")
    print()
    
    # Find all dashboard files
    print_info("Scanning for dashboard files...")
    dashboard_files = find_dashboard_files(input_dir)
    
    if not dashboard_files:
        print_warn(f"No dashboard JSON files found in {input_dir}")
        return False
    
    file_count = len(dashboard_files)
    print_info(f"Found {file_count} dashboard file(s)")
    print()
    
    # Group by folder
    folders = {}
    for df in dashboard_files:
        folder_name = df['folder']
        if folder_name not in folders:
            folders[folder_name] = []
        folders[folder_name].append(df)
    
    print_info(f"Dashboards organized in {len(folders)} folder(s):")
    for folder_name, files in folders.items():
        print(f"  - {folder_name}: {len(files)} dashboard(s)")
    print()
    
    # Get or create target folder ID if specified
    target_folder_id = None
    if target_folder:
        print_step(f"Preparing target folder: {target_folder}")
        target_folder_id = get_or_create_folder(grafana_url, api_key, target_folder, dry_run)
        if target_folder_id:
            folder_msg = f"✓ Using folder '{target_folder}' (ID: {target_folder_id})"
            if dry_run and target_folder_id == -1:
                print_dry_run(folder_msg)
            else:
                print_info(folder_msg)
        else:
            print_warn(f"Will import to original folders instead")
        print()
    
    # Import each dashboard
    imported = 0
    failed = 0
    skipped = 0
    
    for idx, df in enumerate(dashboard_files, 1):
        folder_name = df['folder']
        filename = df['filename']
        
        print_info(f"[{idx}/{file_count}] Importing: {folder_name}/{filename}")
        
        # Read dashboard JSON
        try:
            with open(df['path'], 'r', encoding='utf-8') as f:
                dashboard_json = json.load(f)
        except json.JSONDecodeError as e:
            print_error(f"  ✗ Invalid JSON: {e}")
            failed += 1
            continue
        except IOError as e:
            print_error(f"  ✗ Could not read file: {e}")
            failed += 1
            continue
        
        # Remove ID and UID to avoid conflicts (they'll be regenerated)
        # Keep UID if you want to update existing dashboards
        if 'id' in dashboard_json:
            del dashboard_json['id']
        # Uncomment next line if you want to always create new dashboards
        # if 'uid' in dashboard_json:
        #     del dashboard_json['uid']
        
        # Determine folder ID
        folder_id = target_folder_id
        if folder_id is None and folder_name != 'General':
            # Get or create the original folder
            folder_id = get_or_create_folder(grafana_url, api_key, folder_name, dry_run)
        
        # Import dashboard
        result = import_dashboard(grafana_url, api_key, dashboard_json, folder_id, overwrite, dry_run)
        
        # Check result
        if result.get('error'):
            error_msg = result.get('reason', 'Unknown error')
            if result.get('body'):
                try:
                    error_json = json.loads(result.get('body'))
                    error_msg = error_json.get('message', error_msg)
                except:
                    pass
            print_error(f"  ✗ Failed: {error_msg}")
            failed += 1
        elif result.get('status') == 'success':
            dashboard_uid = result.get('uid', 'unknown')
            dashboard_url = result.get('url', '')
            dashboard_title = result.get('title', dashboard_json.get('title', 'Unknown'))
            if result.get('dry_run'):
                print_dry_run(f"  ✓ Would import '{dashboard_title}' (UID: {dashboard_uid})")
            else:
                print_info(f"  ✓ Imported successfully (UID: {dashboard_uid})")
            imported += 1
        else:
            # Check for specific messages
            message = result.get('message', '')
            if 'already exists' in message.lower():
                print_warn(f"  ⊘ Dashboard already exists (skipped)")
                skipped += 1
            else:
                print_error(f"  ✗ Unknown response: {result}")
                failed += 1
    
    # Summary
    print()
    print_info("=" * 50)
    print_info("Import Summary")
    print_info("=" * 50)
    if dry_run:
        print_dry_run("DRY-RUN MODE - No changes were made")
    print_info(f"Total files: {file_count}")
    print_info(f"Successfully imported: {imported}")
    if skipped > 0:
        print_warn(f"Skipped (already exist): {skipped}")
    if failed > 0:
        print_error(f"Failed: {failed}")
    print_info(f"Input directory: {input_dir}")
    print_info("=" * 50)
    
    return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description='Import Grafana dashboards from JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import from export directory
  %(prog)s --url http://localhost:3000 --api-key YOUR_KEY ./grafana-dashboards-backup-20241105
  
  # Test import without making changes (dry-run)
  %(prog)s --url http://localhost:3000 --api-key YOUR_KEY ./backups --dry-run
  
  # Import to a specific folder
  %(prog)s --url http://localhost:3000 --api-key YOUR_KEY ./backups --folder "Imported"
  
  # Import without overwriting existing
  %(prog)s --url http://localhost:3000 --api-key YOUR_KEY ./backups --no-overwrite

Notes:
  - API key must have Admin or Editor role
  - Dashboard UIDs are preserved (updates existing dashboards with same UID)
  - Folders are created automatically if they don't exist
  - Use --folder to import all dashboards to a single folder
  - Use --dry-run to test without making any changes to Grafana
        """
    )
    
    parser.add_argument('input_dir', metavar='INPUT_DIR', help='Input directory containing dashboard JSON files')
    parser.add_argument('--url', required=True, help='Grafana URL (e.g., http://localhost:3000)')
    parser.add_argument('--api-key', required=True, help='Grafana API key with Admin or Editor role')
    parser.add_argument('--folder', help='Import all dashboards to this folder (creates if needed)')
    parser.add_argument('--no-overwrite', action='store_true', help='Do not overwrite existing dashboards (default: overwrite)')
    parser.add_argument('--dry-run', action='store_true', help='Test mode: show what would be imported without making changes')
    
    args = parser.parse_args()
    
    # Check input directory exists
    if not os.path.isdir(args.input_dir):
        print_error(f"Input directory does not exist: {args.input_dir}")
        sys.exit(1)
    
    # Import dashboards
    overwrite = not args.no_overwrite
    success = import_dashboards(args.url, args.api_key, args.input_dir, args.folder, overwrite, args.dry_run)
    
    if success:
        print_info("Import complete! ✓")
        sys.exit(0)
    else:
        print_error("Import completed with errors")
        sys.exit(1)


if __name__ == '__main__':
    main()