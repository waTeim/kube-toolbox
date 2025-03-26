#!/usr/bin/env python3
import argparse
import ipaddress
import os
import getpass

def parse_memory(mem_str: str) -> int:
    """
    Parse a memory string that may include units (M, MB, G, GB)
    and return the value in megabytes.
    """
    mem_str = mem_str.strip()
    if mem_str.isdigit():
        return int(mem_str)
    mem_str = mem_str.upper()
    if mem_str.endswith("GB"):
        try:
            val = float(mem_str[:-2])
            return int(val * 1024)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid memory specification: {mem_str}")
    elif mem_str.endswith("G"):
        try:
            val = float(mem_str[:-1])
            return int(val * 1024)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid memory specification: {mem_str}")
    elif mem_str.endswith("MB"):
        try:
            val = float(mem_str[:-2])
            return int(val)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid memory specification: {mem_str}")
    elif mem_str.endswith("M"):
        try:
            val = float(mem_str[:-1])
            return int(val)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid memory specification: {mem_str}")
    else:
        raise argparse.ArgumentTypeError("Memory specification must be a number optionally suffixed with M/MB or G/GB")

def parse_disk_size(size_str: str) -> int:
    """
    Parse a disk size string that may include units (M, MB, G, GB)
    and return the size in gigabytes (as an integer).
    """
    size_str = size_str.strip().upper()
    if size_str.isdigit():
        return int(size_str)
    if size_str.endswith("GB"):
        try:
            val = float(size_str[:-2])
            return int(val)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid disk size specification: {size_str}")
    elif size_str.endswith("G"):
        try:
            val = float(size_str[:-1])
            return int(val)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid disk size specification: {size_str}")
    elif size_str.endswith("MB"):
        try:
            val = float(size_str[:-2])
            # Convert MB to GB (round up at least 1GB)
            return max(1, int(val / 1024))
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid disk size specification: {size_str}")
    elif size_str.endswith("M"):
        try:
            val = float(size_str[:-1])
            return max(1, int(val / 1024))
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid disk size specification: {size_str}")
    else:
        raise argparse.ArgumentTypeError("Disk size must be a number optionally suffixed with M/MB or G/GB")

def generate_cloud_init(node_name, ip, prefix, router, root_password, nameservers):
    """
    Generate cloud-init user-data and meta-data with custom netplan configuration.
    This writes a file /etc/netplan/00-local.yaml with the static network config,
    and in runcmd removes the default netplan file so that only the custom one is applied.
    Also, disable_root is set to false and ssh_pwauth is enabled.
    """
    user_data = f"""#cloud-config
disable_root: false
hostname: {node_name}
chpasswd:
  list: |
    root:{root_password}
  expire: false
ssh_pwauth: true
packages:
  - nfs-common
write_files:
  - path: /etc/netplan/00-local.yaml
    content: |
      network:
        version: 2
        ethernets:
          enp1s0:
            dhcp4: false
            addresses:
              - {ip}/{prefix}
            gateway4: {router}
            nameservers:
              addresses: [{nameservers}]
  - path: /etc/ssh/sshd_config.d/00-local.conf
    content: |
      PermitRootLogin yes
      PasswordAuthentication yes
runcmd:
  - rm -f /etc/netplan/50-cloud-init.yaml
  - netplan apply
  - rm -f /etc/ssh/sshd_config.d/50-cloud-init.conf
  - rm -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf
"""
    meta_data = f"""instance-id: {node_name}
local-hostname: {node_name}
"""
    return user_data, meta_data

def main():
    parser = argparse.ArgumentParser(
        description="Generate cloud-init configuration files and virt-install scripts for Kubernetes node VMs."
    )
    parser.add_argument("--cpu", type=int, default=2,
                        help="Number of vCPUs per node (default: 2)")
    parser.add_argument("--memory", type=str, default="2048",
                        help="Memory per node. Can include units (e.g. 2048M, 2G). Default is megabytes if no unit specified (default: 2048)")
    parser.add_argument("--disk-size", type=str, default="10G",
                        help="Disk image size per node. Can include units (e.g. 10G, 10240M). Default is in gigabytes (default: 10G)")
    parser.add_argument("--ip-pattern", required=True,
                        help="IP pattern in the form 'CIDR+/-', e.g. '192.168.1.100/24+' or '192.168.1.100/24-'")
    parser.add_argument("--router", required=True,
                        help="Router IP address (gateway4) for nodes, e.g. '192.168.1.1'")
    parser.add_argument("--nodes", type=int, required=True,
                        help="Number of nodes to generate")
    parser.add_argument("--node-base", type=int, default=1,
                        help="Starting node number (default: 1)")
    parser.add_argument("--ubuntu-image", default="ubuntu-24.04-server-cloudimg-amd64.img",
                        help="Ubuntu cloud image file name (default: ubuntu-24.04-server-cloudimg-amd64.img)")
    parser.add_argument("--image-dir", default="cloud",
                        help="Directory where the Ubuntu cloud images (downloaded via wget) are located (default: cloud)")
    parser.add_argument("--root-password", type=str, default=None,
                        help="Root password for nodes. If not provided, you'll be prompted.")
    parser.add_argument("--nameservers", default="8.8.8.8,8.8.4.4",
                        help="Comma separated list of nameservers (default: 8.8.8.8,8.8.4.4)")
    parser.add_argument("--output-dir", default="config/nodes",
                        help="Output directory for configuration files (default: config/nodes)")

    args = parser.parse_args()

    if args.root_password is None:
        args.root_password = getpass.getpass("Enter root password: ")

    # Parse memory and disk size.
    mem_mb = parse_memory(args.memory)
    disk_size = parse_disk_size(args.disk_size)

    # The ip-pattern must end with '+' or '-' to indicate the direction.
    if args.ip_pattern[-1] not in ['+', '-']:
        parser.error("ip-pattern must end with '+' or '-'")
    direction = args.ip_pattern[-1]
    base_ip_cidr = args.ip_pattern[:-1]  # e.g. "192.168.1.100/24"

    try:
        iface = ipaddress.ip_interface(base_ip_cidr)
    except ValueError as e:
        parser.error(f"Invalid CIDR IP address in ip-pattern: {e}")

    base_ip_int = int(iface.ip)
    prefix = iface.network.prefixlen

    # Process nameservers (ensure proper formatting).
    nameservers_list = ', '.join([s.strip() for s in args.nameservers.split(',')])

    # Determine the backing store image path.
    # Use absolute path for the backing image so it's unambiguous.
    if os.path.isabs(args.ubuntu_image):
        backing_image = args.ubuntu_image
    else:
        backing_image = os.path.join(args.image_dir, args.ubuntu_image)
    backing_image_abs = os.path.abspath(backing_image)

    # Create the output directory for configuration files if it doesn't exist.
    os.makedirs(args.output_dir, exist_ok=True)

    # Loop to generate configuration for each node.
    for i in range(args.node_base, args.node_base + args.nodes):
        node_name = f"node{i}"
        offset = i - args.node_base
        if direction == '+':
            node_ip_int = base_ip_int + offset
        else:
            node_ip_int = base_ip_int - offset
        node_ip = str(ipaddress.ip_address(node_ip_int))

        # Generate cloud-init configuration.
        user_data, meta_data = generate_cloud_init(node_name, node_ip, prefix, args.router, args.root_password, nameservers_list)

        # Write cloud-init files in the config directory.
        node_config_dir = os.path.join(args.output_dir, node_name)
        os.makedirs(node_config_dir, exist_ok=True)
        user_data_file = os.path.join(node_config_dir, "user-data")
        meta_data_file = os.path.join(node_config_dir, "meta-data")
        with open(user_data_file, "w") as ud_file:
            ud_file.write(user_data)
        with open(meta_data_file, "w") as md_file:
            md_file.write(meta_data)

        # Prepare the VM image directory under /var/lib/libvirt/images/<node_name>
        vm_image_dir = os.path.join("/var/lib/libvirt/images", node_name)
        os.makedirs(vm_image_dir, exist_ok=True)

        # Define the disk image and ISO paths.
        disk_path = os.path.join(vm_image_dir, f"{node_name}.qcow2")
        iso_path = os.path.join(vm_image_dir, f"seed-{node_name}.iso")

        # Create the virt-install.sh script that will:
        # 1. Check if the seed ISO exists; if not, generate it using genisoimage.
        # 2. Run virt-install with the given parameters.
        virt_install_script = f"""#!/bin/bash
# Determine absolute path of this script's directory (node config directory)
CONFIG_DIR="$(readlink -f "$(dirname "$0")")"
# Define paths for cloud-init files (assumed to be in the config directory)
USER_DATA="$CONFIG_DIR/user-data"
META_DATA="$CONFIG_DIR/meta-data"

# Define VM image directory and file paths
VM_IMAGE_DIR="{vm_image_dir}"
DISK_PATH="${{VM_IMAGE_DIR}}/{node_name}.qcow2"
ISO_PATH="${{VM_IMAGE_DIR}}/seed-{node_name}.iso"

# Create VM image directory if it doesn't exist
if [ ! -d "${{VM_IMAGE_DIR}}" ]; then
    mkdir -p "${{VM_IMAGE_DIR}}"
fi

# If the seed ISO doesn't exist, generate it using genisoimage
if [ ! -f "${{ISO_PATH}}" ]; then
    echo "Generating seed ISO at ${{ISO_PATH}}..."
    if ! command -v genisoimage >/dev/null 2>&1; then
        echo "Error: genisoimage is not installed. Please install it with: sudo apt install genisoimage" >&2
        exit 1
    fi
    genisoimage -output "${{ISO_PATH}}" -volid cidata -joliet -rock "$USER_DATA" "$META_DATA"
fi

# Run virt-install with the desired parameters
virt-install --name {node_name} \\
  --memory {mem_mb} --vcpus {args.cpu} \\
  --disk path="${{DISK_PATH}}",size={disk_size},backing_store="{backing_image_abs}" \\
  --disk path="${{ISO_PATH}}",device=cdrom \\
  --os-variant ubuntu24.04 --import \\
  --network bridge=br0,model=virtio --graphics none
"""
        # Write the virt-install.sh script to the node's config directory.
        virt_install_file = os.path.join(node_config_dir, "virt-install.sh")
        with open(virt_install_file, "w") as vif:
            vif.write(virt_install_script)
        # Make the script executable.
        os.chmod(virt_install_file, 0o755)

        print(f"Configuration for {node_name} generated in {node_config_dir}")
        print(f"Virt-install script written to {virt_install_file}")
        print(f"VM image files will be placed in {vm_image_dir}")
        print("-" * 60)

if __name__ == "__main__":
    main()
