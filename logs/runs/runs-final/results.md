
## Scenario compare (official.img)

- console login at 83s; units and order saved as compare-official.units.txt / compare-official.order.txt
```
mnt-overlay.mount 12436076
mnt-data.mount 22770003
haos-data-unlock.service 0
sysinit.target 35910693
basic.target 36006342
network-online.target 41176175
docker.service 76760298
haos-supervisor.service 77836474
multi-user.target 77891157
3193523
systemd-time-wait-sync.service loaded failed failed Wait Until Kernel Time Synchronized
systemd-analyze: not in the image
```

## Scenario compare (plain.img)

- console login at 90s; units and order saved as compare-plain.units.txt / compare-plain.order.txt
```
mnt-overlay.mount 16299052
mnt-data.mount 28109563
haos-data-unlock.service 0
sysinit.target 40534301
basic.target 40618312
network-online.target 46601304
docker.service 83082750
haos-supervisor.service 85077366
multi-user.target 85198624
4626445
systemd-time-wait-sync.service loaded failed failed Wait Until Kernel Time Synchronized
systemd-analyze: not in the image
```
