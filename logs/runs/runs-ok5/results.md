
## Scenario key-ok

- console login after 106s, data+docker active: **True** (at 107s)
- Supervisor ran its resolution checks: **True** (at 172s)
### unit states
```
$ systemctl is-active haos-data-unlock.service mnt-data.mount var-lib-docker.mount var-log-journal.mount containerd.service docker.service haos-supervisor.service; true
active
active
active
active
active
active
active
```
### failed units
```
$ systemctl --failed --no-legend --plain
haos-expand.service            loaded failed failed HAOS data resizing
haos-swapfile.service          loaded failed failed HAOS swap
systemd-time-wait-sync.service loaded failed failed Wait Until Kernel Time Synchronized
```
### ordering cycles
```
$ journalctl -b --no-pager | grep -i -E 'ordering cycle|breaking ordering' || echo none
none
```
### unlock log
```
$ journalctl -b -u haos-data-unlock --no-pager -o short-monotonic | tail -n 12
[   55.400048] homeassistant systemd[1]: Starting HAOS data partition unlock (network key)...
[   56.465408] homeassistant haos-data-unlock[450]: [INFO] Key provider: https
[   58.501306] homeassistant haos-data-unlock[450]: [INFO] Data partition unlocked with the https key (attempt 1)
[   58.741010] homeassistant systemd[1]: Finished HAOS data partition unlock (network key).
```
### expand log
```
$ journalctl -b -u haos-expand --no-pager -o cat | tail -n 8
Using 8 out of 128 partitions.
A total of 2014 free sectors is available in 1 segment.
[INFO] Resize dm-crypt mapping hassos-data
Nothing to read on input.
haos-expand.service: Main process exited, code=exited, status=1/FAILURE
haos-expand.service: Failed with result 'exit-code'.
Failed to start HAOS data resizing.
haos-expand.service: Consumed 2.880s CPU time, 5.6M memory peak.
```
### block devices
```
$ lsblk -o NAME,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS /dev/vda
NAME            TYPE   SIZE FSTYPE      LABEL          MOUNTPOINTS
vda             disk     6G                            
|-vda1          part    32M vfat        hassos-boot    /mnt/boot
|-vda2          part    24M squashfs                   
|-vda3          part   256M erofs                      /
|-vda4          part    24M                            
|-vda5          part   256M                            
|-vda6          part     8M                            
|-vda7          part    96M ext4        hassos-overlay /var/lib/NetworkManager
|                                                      /etc/hosts
|                                                      /etc/systemd/timesyncd.conf.d
|                                                      /etc/hostname
|                                                      /etc/NetworkManager/system-connections
|                                                      /etc/modules-load.d
|                                                      /root/.ssh
|                                                      /var/lib/bluetooth
|                                                      /etc/usb_modeswitch.d
|                                                      /etc/sysctl.d
|                                                      /etc/modprobe.d
|                                                      /var/lib/systemd
|                                                      /root/.docker
|                                                      /etc/udev/rules.d
|                                                      /etc/default
|                                                      /etc/dropbear
|                                                      /mnt/overlay
`-vda8          part   5.3G crypto_LUKS                
  `-hassos-data crypt  952M ext4        hassos-data    /var/log/journal
                                                       /var/lib/docker
                                                       /mnt/data
```
### crypt status
```
$ cryptsetup status hassos-data | head -n 8
/dev/mapper/hassos-data is active and is in use.
  type:    LUKS2
  cipher:  aes-xts-plain64
  keysize: 512 [bits]
  key location: keyring
  device:  /dev/vda8
  sector size:  512 [bytes]
  offset:  32768 [512-byte units] (16777216 [bytes])
```
### data mount
```
$ findmnt /mnt/data; df -h /mnt/data | tail -n 1
TARGET    SOURCE                  FSTYPE OPTIONS
/mnt/data /dev/mapper/hassos-data ext4   rw,relatime,commit=30
                        900.8M    640.5M    196.7M  77% /mnt/data
```
### journal persistent
```
$ findmnt /var/log/journal; ls /mnt/data/logs | head -n 3
TARGET           SOURCE                         FSTYPE OPTIONS
/var/log/journal /dev/mapper/hassos-data[/logs] ext4   rw,relatime,commit=30
2ab7967918154a53b5189f4e19e7390b
```
### timing (monotonic, microseconds)
```
$ for u in haos-data-unlock.service mnt-data.mount docker.service haos-supervisor.service; do echo "$u $(systemctl show -P ActiveEnterTimestampMonotonic $u)"; done
haos-data-unlock.service 58740779
mnt-data.mount 62907543
docker.service 98036595
haos-supervisor.service 100655245
```
### swap
```
$ swapon --show; free -m | head -n 3
total        used        free      shared  buff/cache   available
Mem:            1966         276        1247           0         474        1689
Swap:              0           0           0
```
### containers
```
$ docker ps -a --format '{{.Names}} {{.Status}}' | head
hassio_supervisor Up About a minute
```
### data disk as seen by udisks2 / os-agent
```
$ busctl get-property org.freedesktop.UDisks2 /org/freedesktop/UDisks2/block_devices/dm_2d0 org.freedesktop.UDisks2.Block Device; busctl get-property io.hass.os /io/hass/os/DataDisk io.hass.os.DataDisk CurrentDevice
ay 10 47 100 101 118 47 100 109 45 48 0
s ""
```
### supervisor data disk issues
```
$ docker logs hassio_supervisor 2>&1 | grep -i -E 'data.?disk|multiple' | tail -n 8; docker exec hassio_cli ha resolution info --raw-json 2>/dev/null | head -c 1500; echo

```
### slot / boot counter
```
$ cat /proc/cmdline | tr ' ' '\n' | grep -E 'rauc.slot|systemd.unit'; grep -a -E '^(ORDER|A_OK|A_TRY|B_OK|B_TRY)=' /mnt/boot/EFI/BOOT/grubenv | tr '\n' ' '; echo
rauc.slot=A
ORDER=A B A_OK=1 A_TRY=1 B_TRY=0 B_OK=0
```
