# DS4 parallel PXE login rescue

This service is stage one of Spark recovery. It serves the same signed ARM64
UEFI boot chain to every PXE client and boots each Spark's installed root into
`multi-user.target`. It does not modify the client disk, keys, boot order, or
system policy.

The rescue kernel command line masks only:

- `ds4-switched-fabric.service`
- `ds4-direct-pair-fabric.service`

Management networking is acquired with DHCP on `enP7s7`. The installed root is
mounted from `/dev/nvme0n1p2`, matching the commissioned Spark layout. The PXE
server uses Microsoft's signed ARM64 shim followed by Canonical's signed GRUB,
so Secure Boot remains enabled.

## Deploy and start

Run from a clean, committed checkout:

```bash
python3 scripts/ds4_parallel_pxe_rescue.py deploy --server spark0
python3 scripts/ds4_parallel_pxe_rescue.py start --server spark0
python3 scripts/ds4_parallel_pxe_rescue.py status --server spark0 --require-active
```

The service is deliberately not enabled at server boot. Multiple Sparks may be
PXE-booted concurrently while it is active.

## Stage two

After rescued nodes reach login, apply and audit the permanent policy in
parallel:

```bash
python3 scripts/ds4_spark_brickproof.py apply \
  --nodes spark1,spark9,sparka,sparkb,sparkc,sparkd,sparke,sparkf \
  --jobs 8
```

Stop PXE service after recovery:

```bash
python3 scripts/ds4_parallel_pxe_rescue.py stop --server spark0
```

Every controller action writes a JSON receipt under the local temporary
directory. `status --require-active` fails if the signed assets differ from the
manifest, DHCP/TFTP listeners are absent, the temporary firewall rule is absent,
or the service is unexpectedly enabled persistently.
