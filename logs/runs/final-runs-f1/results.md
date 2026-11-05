
## Scenario key-ok

- console login after 190s, data+docker active: **True** (at 191s)
- Supervisor ran its resolution checks: **True** (at 253s)
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
[   80.879935] homeassistant systemd[1]: Starting HAOS data partition unlock (network key)...
[   82.202370] homeassistant haos-data-unlock[504]: [INFO] Key provider: https
[   87.553435] homeassistant haos-data-unlock[504]: [INFO] Data partition unlocked with the https key (attempt 1)
[   88.040646] homeassistant systemd[1]: Finished HAOS data partition unlock (network key).
```
### expand log
```
$ journalctl -b -u haos-expand --no-pager -o cat | tail -n 8
[INFO] Checking if expanding data partition on /dev/vda8 is necessary
[INFO] Detected GPT partition label on /dev/vda
[INFO] Last usable logical block 12582878
[INFO] Data partition end block 12582879
[INFO] No resize of data partition needed
haos-expand.service: Deactivated successfully.
Finished HAOS data resizing (encrypted data partition).
haos-expand.service: Consumed 3.032s CPU time, 2M memory peak.
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
|                                                      /etc/hostname
|                                                      /etc/systemd/timesyncd.conf.d
|                                                      /etc/hosts
|                                                      /etc/NetworkManager/system-connections
|                                                      /var/lib/systemd
|                                                      /var/lib/bluetooth
|                                                      /root/.docker
|                                                      /root/.ssh
|                                                      /etc/modules-load.d
|                                                      /etc/udev/rules.d
|                                                      /etc/modprobe.d
|                                                      /etc/usb_modeswitch.d
|                                                      /etc/sysctl.d
|                                                      /etc/dropbear
|                                                      /etc/default
|                                                      /mnt/overlay
`-vda8          part   5.3G crypto_LUKS                
  `-hassos-data crypt  5.3G ext4        hassos-data    /var/log/journal
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
/mnt/data /dev/mapper/hassos-data ext4   rw,relatime,commit=30,mb_optimize_scan=0
                          5.2G      1.6G      3.3G  33% /mnt/data
```
### journal persistent
```
$ findmnt /var/log/journal; ls /mnt/data/logs | head -n 3
TARGET           SOURCE                         FSTYPE OPTIONS
/var/log/journal /dev/mapper/hassos-data[/logs] ext4   rw,relatime,commit=30,mb_optimize_scan=0
ef4854f6292a47e98c3600d91ea45a2f
```
### timing (monotonic, microseconds)
```
$ for u in haos-data-unlock.service mnt-data.mount docker.service haos-supervisor.service; do echo "$u $(systemctl show -P ActiveEnterTimestampMonotonic $u)"; done
haos-data-unlock.service 88030694
mnt-data.mount 91939528
docker.service 178932630
haos-supervisor.service 182964576
```
### swap
```
$ swapon --show; free -m | head -n 3
NAME               TYPE  SIZE USED PRIO
/mnt/data/swapfile file 1024M   0B   -2
               total        used        free      shared  buff/cache   available
Mem:            1966         326          95           0        1576        1639
Swap:           1023           0        1023
```
### containers
```
$ docker ps -a --format '{{.Names}} {{.Status}}' | head
hassio_audio Up 4 seconds
hassio_dns Up 8 seconds
hassio_cli Up 13 seconds
hassio_supervisor Up About a minute
```
### data disk as seen by udisks2 / os-agent
```
$ busctl get-property org.freedesktop.UDisks2 /org/freedesktop/UDisks2/block_devices/dm_2d0 org.freedesktop.UDisks2.Block Device; busctl get-property io.hass.os /io/hass/os/DataDisk io.hass.os.DataDisk CurrentDevice
ay 10 47 100 101 118 47 100 109 45 48 0
s "/dev/mapper/hassos-data"
```
### supervisor data disk issues
```
$ docker logs hassio_supervisor 2>&1 | grep -i -E 'data.?disk|multiple' | tail -n 8; docker exec hassio_cli ha resolution info --raw-json 2>/dev/null | head -c 1500; echo
{"result":"error","message":"System is not ready with state: setup"}
```
### slot / boot counter
```
$ cat /proc/cmdline | tr ' ' '\n' | grep -E 'rauc.slot|systemd.unit'; grep -a -E '^(ORDER|A_OK|A_TRY|B_OK|B_TRY)=' /mnt/boot/EFI/BOOT/grubenv | tr '\n' ' '; echo
rauc.slot=A
ORDER=A B A_OK=1 A_TRY=1 B_TRY=0 B_OK=0
```

## Scenario key-denied (+ recovery passphrase on the console)

- recovery passphrase prompt on the console: **True** (at 35s)
- passphrase typed at 95s, console login at 137s, data+docker active: **True** (at 138s)
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
[   29.614599] homeassistant systemd[1]: Starting HAOS data partition unlock (network key)...
[   30.302640] homeassistant haos-data-unlock[496]: [INFO] Key provider: https
[   31.853627] homeassistant haos-data-unlock[496]: [INFO] Data partition unlocked with the https key (attempt 1)
[   32.052354] homeassistant systemd[1]: Finished HAOS data partition unlock (network key).
```
### expand log
```
$ journalctl -b -u haos-expand --no-pager -o cat | tail -n 8
[INFO] Checking if expanding data partition on /dev/vda8 is necessary
[INFO] Detected GPT partition label on /dev/vda
[INFO] Last usable logical block 12582878
[INFO] Data partition end block 12582879
[INFO] No resize of data partition needed
haos-expand.service: Deactivated successfully.
Finished HAOS data resizing (encrypted data partition).
haos-expand.service: Consumed 1.083s CPU time, 2.2M memory peak.
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
|-vda7          part    96M ext4        hassos-overlay /etc/systemd/timesyncd.conf.d
|                                                      /var/lib/NetworkManager
|                                                      /etc/hostname
|                                                      /etc/NetworkManager/system-connections
|                                                      /etc/hosts
|                                                      /root/.ssh
|                                                      /var/lib/systemd
|                                                      /var/lib/bluetooth
|                                                      /root/.docker
|                                                      /etc/modprobe.d
|                                                      /etc/usb_modeswitch.d
|                                                      /etc/modules-load.d
|                                                      /etc/udev/rules.d
|                                                      /etc/sysctl.d
|                                                      /etc/default
|                                                      /etc/dropbear
|                                                      /mnt/overlay
`-vda8          part   5.3G crypto_LUKS                
  `-hassos-data crypt  5.3G ext4        hassos-data    /var/log/journal
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
/mnt/data /dev/mapper/hassos-data ext4   rw,relatime,commit=30,mb_optimize_scan=0
                          5.2G      1.6G      3.3G  33% /mnt/data
```
### journal persistent
```
$ findmnt /var/log/journal; ls /mnt/data/logs | head -n 3
TARGET           SOURCE                         FSTYPE OPTIONS
/var/log/journal /dev/mapper/hassos-data[/logs] ext4   rw,relatime,commit=30,mb_optimize_scan=0
64ac0d6a00f04a90bf95617ee4c79325
```
### timing (monotonic, microseconds)
```
$ for u in haos-data-unlock.service mnt-data.mount docker.service haos-supervisor.service; do echo "$u $(systemctl show -P ActiveEnterTimestampMonotonic $u)"; done
haos-data-unlock.service 32051771
mnt-data.mount 91466995
docker.service 129433695
haos-supervisor.service 131661262
```
### swap
```
$ swapon --show; free -m | head -n 3
NAME               TYPE  SIZE USED PRIO
/mnt/data/swapfile file 1024M   0B   -2
               total        used        free      shared  buff/cache   available
Mem:            1966         225         332           0        1440        1741
Swap:           1023           0        1023
```
### containers
```
$ docker ps -a --format '{{.Names}} {{.Status}}' | head
hassio_supervisor Created
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

## Scenario wipe (haos.wipe=1 on an encrypted system)

### boot 1 (encrypted), wipe requested
```
NAME          TYPE  FSTYPE      LABEL
vda8          part  crypto_LUKS 
`-hassos-data crypt ext4        hassos-data
console=tty0 console=ttyS0 haos.data-crypt=1 haos.wipe=1
```
### boot 2 (console login at 160s)
```
console=tty0 console=ttyS0
/dev/vda8: LABEL="hassos-data" UUID="408096f9-5a00-48af-af0e-8d0c61ff4f4a" BLOCK_SIZE="4096" TYPE="ext4" PARTLABEL="hassos-data" PARTUUID="a52a4597-fa3a-4851-aefd-2fbe9f849079"
not-LUKS
/dev/vda8
ls: /mnt/overlay/etc/haos-data-crypt: No such file or directory
mke2fs 1.47.2 (1-Jan-2025)
Discarding device blocks:     0/98304           done
Creating filesystem with 98304 1k blocks and 24576 inodes
Filesystem UUID: cf4d60c0-9b5f-48c3-bfd3-a497b1ab0ee5
Superblock backups stored on blocks:
	8193, 24577, 40961, 57345, 73729
Allocating group tables:  0/12     done
Writing inode tables:  0/12     done
Creating journal (4096 blocks): done
Writing superblocks and filesystem accounting information:  0/12     done
[INFO] Removing wipe and data encryption flags from cmdline.txt
Finished Home Assistant OS Device Wipe Service.
0
haos-apparmor.service          loaded failed failed HAOS AppArmor
systemd-time-wait-sync.service loaded failed failed Wait Until Kernel Time Synchronized
```
### boot 3 (console login at 130s)
```
console=tty0 console=ttyS0
/dev/vda8: LABEL="hassos-data" UUID="408096f9-5a00-48af-af0e-8d0c61ff4f4a" BLOCK_SIZE="4096" TYPE="ext4" PARTLABEL="hassos-data" PARTUUID="a52a4597-fa3a-4851-aefd-2fbe9f849079"
not-LUKS
/dev/vda8
ls: /mnt/overlay/etc/haos-data-crypt: No such file or directory
Home Assistant OS Device Wipe Service was skipped because of an unmet condition check (ConditionKernelCommandLine=haos.wipe=1).
0
haos-apparmor.service          loaded failed failed HAOS AppArmor
systemd-time-wait-sync.service loaded failed failed Wait Until Kernel Time Synchronized
```

## Scenario locked-reboots (3 power cuts while locked, then key back)

- locked boot 1: kernel slot A, rescue entry: False, recovery prompt: True; grubenv after power cut: `ORDER=A B A_OK=1 A_TRY=1 B_TRY=0 B_OK=0 MACHINE_ID=489213fb8bdd498c877631c3183385db`
- locked boot 2: kernel slot A, rescue entry: False, recovery prompt: True; grubenv after power cut: `ORDER=A B A_OK=1 A_TRY=2 B_TRY=0 B_OK=0 MACHINE_ID=489213fb8bdd498c877631c3183385db`
- locked boot 3: kernel slot A, rescue entry: False, recovery prompt: True; grubenv after power cut: `ORDER=A B A_OK=1 A_TRY=3 B_TRY=0 B_OK=0 MACHINE_ID=489213fb8bdd498c877631c3183385db`
- boot 4 with key server up: kernel command line slot A, rescue entry: True
- boot 4: **no console login** (locked-boot4: 'homeassistant login: ' not seen within 900s); serial log in locked-boot4.serial.log
