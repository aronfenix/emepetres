# Device build and recovery evidence

Status on 2026-11-12: development verification only. No player connection,
card writes, firmware installation, or tested recovery procedure.

## Compiler verification

The existing two simulator builds cannot establish target ABI, driver linkage,
bootloader size or an actual boot. The separate
`emepetres-target-build.yml` workflow builds the exact compilers specified by
`tools/rockboxdev.sh` and `tools/configure`: GCC 9.5.0 with binutils 2.38.
It compiles both the application and bootloader for hosted `agptekrocker`
and native `agptekrockernative` in separate runner directories. Completed
toolchains are cached by architecture and the compiler-script/patch hash.
This work runs on GitHub; it installs no development tools on the user's PC.

Results are compiler outputs labelled UNVERIFIED-ON-HARDWARE. They contain
no patched `.upt` update. The legacy update-patching script is not executed.
The old prebuilt Docker image mentioned in `tools/docker_rbclient/README`
was rejected for this check: its latest Docker Hub tag was updated in 2019
and is not evidence for the repository's current compiler version.

## Original vendor image found

Source: [AGPTEK's Rocker firmware page](https://www.agptek.com/index.php/blog/agptek-rocker-firmware-download-2/),
the download labelled UPT1.1, dated 2017-03-06:
[original update.upt](https://images.agptek.us/image/ROCKERVersion/ROCKERVersion1.1/update.upt).

Downloaded read-only for analysis. It has 32,466,944 bytes; SHA-256:

`d56d5b093477ad32ad50d41f09155d23c9f9a458993d2e40e800dd704c73b8e6`

It is an ISO9660 image, volume CDROM, containing `uboot.bin`, `uimage.bin`,
`system.ubi`, `update.txt`, `version.txt` and a small extra file. The three
payload MD5s match the internal update manifest:

| Payload | Bytes | Manifest MD5 |
| --- | ---: | --- |
| uboot.bin | 348,968 | 67dd21eaf39843132bbd31b002cf483c |
| uimage.bin | 2,549,215 | cbd1a60352eac99dc441ec14df2590d3 |
| system.ubi | 29,204,480 | f1e31fcdf0d6e765fc41740ca09fa9c9 |

These checks establish internal consistency, not an independently signed
vendor checksum. Despite the download label 1.1, `version.txt` says
`name=k1`, `ver=1.0.0.0`. Neither label identifies the user's exact hardware.
The manifest requests `full_upgrade=yes` for rootfs and also includes U-Boot:
this is not a harmless SD-only application update.

At inspection time, the same vendor page's 2017-11-01 and 2018-12-07 links
returned HTTP 404. The hosted installation manual in this checkout explicitly
lists stock firmware 20171101 as its supported binary-patch input. Therefore
the downloaded 1.1 image must not be assumed suitable for that patch.

## Recovery code evidence and limits

The native X1000 header defines VOL- as its recovery key and notes that it
is also the original U-Boot recovery key. It defines Hiby player/recovery
flash ranges and a bootloader-backup filename `/agptekrocker-boot.bin`.
The native installer supports backup and restore of that bootloader region.
These are source-code facts, not a verified recovery recipe for this device,
and a bootloader-region backup is not a complete NAND/rootfs backup.

The hosted target instead starts inside the manufacturer's Linux environment.
Its `rockbox.rocker` and bootloader cannot be exchanged with the native target's
`rockbox.rockern` and `bootloader.rockern`.

Before an installation kit: identify the physical revision and current boot
state, obtain a matching original image and practical recovery method,
review completed target builds, and use separate test storage. Preserve the
existing 64 GB music card; no formatting or installation is authorized here.
