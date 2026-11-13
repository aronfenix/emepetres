# Device build and recovery evidence

Status on 2026-11-13: development verification and read-only USB inspection.
No card writes, firmware installation, or tested recovery procedure.

## Connected player and existing storage

Windows identifies the connected USB disk as AGPTEK ROCKER, 63,864,569,856
bytes, MBR partition table. Its single visible music volume is exFAT,
63,831,015,424 bytes with 4,179,755,008 bytes free and a Healthy status.
No `.rockbox` directory or update image is present at its root. This does not
prove which bootloader is installed internally. No music contents were modified.

The user has no spare card and authorized using this card while retaining
the music. Formatting is not part of that authorization. This makes the
hosted port the preferred investigation path: native `firmware/common/fat.c`
implements FAT16/FAT32 and does not implement exFAT. The hosted bootloader
instead invokes the stock Linux mount command, so its actual exFAT behavior
must be verified in the original environment before a compatibility claim.

## Compiler verification

The existing two simulator builds cannot establish target ABI, driver linkage,
bootloader size or an actual boot. The separate
`emepetres-target-build.yml` workflow builds the exact compilers specified by
`tools/rockboxdev.sh` and `tools/configure`: GCC 9.5.0 with binutils 2.38.
It compiles both the application and bootloader for hosted `agptekrocker`
and native `agptekrockernative` in separate runner directories. Completed
toolchains are cached by architecture and the compiler-script/patch hash.
This work runs on GitHub; it installs no development tools on the user's PC.

The native job in [run 43276572060](https://github.com/aronfenix/emepetres/actions/runs/43276572060/job/131386431724)
completed successfully from `9b56f100abb7c824668ca3fb8a35332d290d1dfe`,
using `mipsel-elf-gcc (GCC) 9.5.0`. Downloaded compiler-output checksums match
the runner manifest. The application is 1,100,488 bytes and the bootloader
archive is 92,160 bytes, containing SPL, UCL payload and version information.
The native package includes the emepetres navigation configuration and Last.fm
export plugin.

The hosted job in the same run also completed successfully, using
`mipsel-rockbox-linux-gnu-gcc (GCC) 9.5.0`. Its application is 1,273,416 bytes,
bootloader 107,184 bytes, and package 13,802,128 bytes. Downloaded SHA-256s
match the runner manifest; navigation configuration and Last.fm plugin are
present. The core, bootloader and plugin are little-endian ELF32 MIPS. The
executables request `/lib/ld.so.1`; required versioned symbols are GLIBC 2.0
through 2.3.2, plus ALSA 0.9 / 0.9.0rc4. This inspects build requirements;
comparison with the vendor's extracted libraries remains pending.

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

The legacy uImage header names Linux 3.10.14; both its header and payload CRC32
match. Its gzip-expanded kernel contains the exFAT driver's mount/read/write
messages. This is concrete evidence that the downloaded vendor kernel includes
exFAT support, but does not prove that the user's unit runs identical bytes or
that the hosted bootloader's mount invocation succeeds on this card.

At inspection time, the same vendor page's 2017-11-01 and 2018-12-07 links
returned HTTP 404. The hosted installation manual in this checkout explicitly
lists stock firmware 20171101 as its supported binary-patch input. Therefore
the downloaded 1.1 image must not be assumed suitable for that patch.

## Reproducible vendor-library audit

The dedicated `emepetres-vendor-audit.yml` workflow is prepared; its first full
vendor extraction/comparison run is still pending. Local parser tests do not
establish a match with the actual vendor libraries. Do not interpret this
section as a successful vendor ABI or device verification result.

The workflow uses the already successful hosted artifact
`emepetres-agptekrocker-UNVERIFIED-ON-HARDWARE` from run `43276572060`; it does
not rebuild firmware. Before downloading it, the workflow checks the GitHub
run's successful conclusion, originating workflow and exact source revision
`9b56f100abb7c824668ca3fb8a35332d290d1dfe`. The audit finds the artifact's
metadata even when cross-run download preserves the nested
`emepetres/emepetres` common directory. It verifies every manifest SHA-256,
requires all three hosted outputs to be covered, and checks that the packaged
core is identical to the standalone core.

Only the disposable Ubuntu runner downloads and unpacks the vendor image.
The ISO's exact byte count/SHA-256 and three internal MD5s must match before
rootfs extraction. `system.ubi` is passed to the extractor as supplied;
the extractor supports both raw UBIFS and an outer UBI container, so the
filename is not treated as proof of either format. The extractor is
[`ubi-reader` 0.8.16](https://pypi.org/project/ubi-reader/0.8.16/), maintained
in [onekey-sec/ubi_reader](https://github.com/onekey-sec/ubi_reader). Its
official Python wheel is SHA-256 checked before installation:

`c3d05e19c8fa760061d0e32cf92e6c15c62c8d6fd2c9c64f085d2299ea924800`

The runner records its installed Python packages and GNU `readelf` version.
No extractor or development dependency is installed on the user's PC. The
audit never runs vendor executables, target executables, startup scripts,
mount commands, update tools or the legacy firmware patcher. Extraction
errors and warnings about missing/corrupted file data fail the audit;
unprivileged skips of special device nodes are permitted because those nodes
are not needed to read ELF metadata.

`tools/emepetres/vendor_audit.py` inspects the hosted application,
bootloader and packaged Last.fm plugin, then follows their actual vendor
library dependencies. Its checks include:

- ELF32, little-endian MIPS, interpreter availability, o32/n32/64 ABI flags,
  ISA/architecture-extension flags, NaN encoding and available floating-point
  ABI attributes. Differences fail conservatively for review.
- Every required dynamic library and version namespace, plus each individual
  imported symbol and its exact version. The symbol's version index identifies
  its actual provider; an identically named GLIBC namespace in another library
  cannot supply a false match. Unversioned imports require an unversioned or
  default-version export. Missing weak imports are listed separately.
- Transitive dependencies and the vendor loader, including the loader inherited
  by a plugin with no interpreter of its own. Vendor absolute symlinks resolve
  inside the extracted virtual root, never the runner's `/lib`.
- Numbered excerpts and SHA-256s for stock mount, startup and recovery-related
  text files where found. Missing categories, missing FP attributes and runtime
  RPATH/RUNPATH evidence are recorded explicitly as unresolved.

The reports model library lookup in `/lib` then `/usr/lib`; an actual runtime
loader/cache configuration, symbol interposition, unsupported instructions,
audio drivers and all device behavior remain untested. Different ISA/FP flags
may require investigation rather than proving that a binary cannot run.
`STATIC_CHECKS_PASSED_WITH_UNRESOLVED_EVIDENCE_UNVERIFIED_ON_HARDWARE` means
the checked requirements passed but the listed static questions remain open.
Neither passing status validates installation or physical recovery.

The workflow uploads only JSON/Markdown reports, `readelf` text and text logs
under `emepetres-vendor-static-audit-UNVERIFIED-ON-HARDWARE`. The original
image, rootfs, extracted scripts/libraries and compiler package stay in runner
temporary storage and are not uploaded or cached. The workflow produces no
patched `.upt`, installer or installation kit.

Maintainer execution after integrating this change:

```text
gh workflow run emepetres-vendor-audit.yml --ref emepetres/dev
```

Review the run summary plus `vendor-audit.json` and extraction/readelf logs;
record that run's URL and actual findings here before claiming vendor-library
compatibility. If the original build artifact has expired, report that missing
input rather than substituting another build silently.

Local verification on 2026-11-13: 23 audit unit tests, 21 passed and two
symlink tests skipped because this Windows session cannot create symlinks.
Those two tests run on the Ubuntu audit runner. The fixtures cover symbol
versions/providers, missing libraries/namespaces, MIPS flag differences,
artifact hashes/paths, nested artifact roots, package identity, extraction
diagnostics and stock-script excerpts. They use no device, vendor execution,
network requests, user music or credentials.

## Recovery code evidence and limits

The native X1000 header defines VOL- as its recovery key and notes that it
is also the original U-Boot recovery key. It defines Hiby player/recovery
flash ranges and a bootloader-backup filename `/agptekrocker-boot.bin`.
The native installer supports backup and restore of that bootloader region.
These are source-code facts, not a verified recovery recipe for this device,
and a bootloader-region backup is not a complete NAND/rootfs backup.

`utils/jztool/src/x1000.c` also offers USB loading into SRAM/DRAM and the
bootloader's USB flag enters recovery without automatically selecting Install.
Its Rocker USB-boot key is VOL+, distinct from the VOL- recovery-menu key.
On Windows this requires the appropriate WinUSB driver; no driver was installed
and no USB loader was run. Even this path cannot use the current exFAT card
with the native FAT-only storage code, and is not a validated rollback method.

The hosted target instead starts inside the manufacturer's Linux environment.
Its `rockbox.rocker` and bootloader cannot be exchanged with the native target's
`rockbox.rockern` and `bootloader.rockern`.

Before an installation kit: identify the physical revision and current boot
state, obtain a matching original image and practical recovery method,
review completed target builds, and use compatible storage without formatting
the existing music card. Additional test files may be considered under the
user's authorization; firmware installation remains a separate blocked step.
