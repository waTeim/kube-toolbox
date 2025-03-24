# Multi-Node Cloud-Init & virt-install Generator

This Python script automates the generation of cloud-init
configuration files and virt-install scripts for creating
multiple Kubernetes node VMs on a KVM/libvirt host running
Ubuntu. It generates custom network and SSH configurations to
enable static IP assignment and root login via password.

## Features

- Supports multiple nodes in one run.
- Generates a netplan file at
  `/etc/netplan/00-local.yaml` for static IP configuration.
- Creates an SSH config file at
  `/etc/ssh/sshd_config.d/00-local.conf` to enable root login.
- Removes default config files (e.g.,
  `50-cloud-init.yaml`, `50-cloud-init.conf`, and
  `60-cloudimg-settings.conf`) via runcmd.
- The virt-install script generates a seed ISO if needed.
- Organizes output in per-node directories.

## Prerequisites

- Python 3 must be installed.
- Install `genisoimage` (e.g., on Ubuntu run:
  `sudo apt update && sudo apt install genisoimage`).
- KVM, libvirt, and `virt-install` must be set up.
- The Ubuntu cloud image must exist in the specified image
  directory (default: `cloud`).

## Usage

Run the script with required options. For example:

    python3 mk-node-defs.py --cpu 2 --memory 2048 --disk-size 10G \
      --ip-pattern 192.168.1.100/24+ --router 192.168.1.1 --nodes 3 \
      --node-base 1 --ubuntu-image ubuntu-24.04-server-cloudimg-amd64.img

### Options

* `--cpu`: vCPUs per node (default: 2)
* `--memory`: Memory per node (e.g., 2048, 2048M, 2G; default is MB)
* `--disk-size`: Disk size (e.g., 10G, 10240M; default is in GB)
* `--ip-pattern`: IP pattern in CIDR format with a trailing '+' or '-'
* `--router`: Router (gateway) IP address
* `--nodes`: Number of nodes to generate
* `--node-base`: Starting node number (default: 1)
* `--ubuntu-image`: Ubuntu cloud image filename (default:
  ubuntu-24.04-server-cloudimg-amd64.img)
* `--image-dir`: Directory for Ubuntu cloud images (default: cloud)
* `--root-password`: Root password (prompted if not given)
* `--nameservers`: Comma-separated nameservers (default:
  8.8.8.8,8.8.4.4)
* `--output-dir`: Directory for output configs (default:
  config/nodes)

## Generated Files

For each node (e.g., node1, node2, ...), the script creates:

- **Cloud-init files:**
  - `user-data`: Contains cloud-init configuration with network and SSH
    settings.
  - `meta-data`: Contains instance metadata.
- **Virt-install script:**
  - `virt-install.sh`: A script that (1) generates a seed ISO from the
    cloud-init files if missing, and (2) runs virt-install with the
    specified parameters.
- VM disk images and seed ISOs are stored in
  `/var/lib/libvirt/images/nodeX`.

## Cloud-Init Configuration Details

The cloud-init configuration in `user-data` includes:

- **Root Login:**
  - `disable_root: false`
  - `ssh_pwauth: True`
  - Sets the root password via `chpasswd`.
- **Network Settings:**
  - Writes a netplan file at `/etc/netplan/00-local.yaml` to assign
    a static IP to interface `enp1s0`.
- **SSH Settings:**
  - Writes a file at `/etc/ssh/sshd_config.d/00-local.conf` with:
    - `PermitRootLogin yes`
    - `PasswordAuthentication yes`
- **Cleanup Commands (runcmd):**
  - Removes default configuration files that may override your
    custom settings.

## License

This project is licensed under the MIT License. See the LICENSE file
for details.

## Contributing

Contributions and suggestions are welcome. Please open an issue or
submit a pull request.

## Disclaimer

Use this script at your own risk. Enabling root SSH login and password
authentication can pose security risks. For production, it is
recommended to use SSH keys and non-root sudo users.
