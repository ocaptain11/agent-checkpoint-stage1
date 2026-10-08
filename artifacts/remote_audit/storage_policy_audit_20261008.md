# Storage policy audit — 2026-10-08

Collected on `infinite-frontier` as user `yishi` through the approved
`factlab-cf → mantis → infinite-frontier` SSH path. The audit was read-only
with respect to the legacy project.

| Root | Mount | `df -hT` observed | Top-level user usage | Policy role |
|---|---|---:|---:|---|
| `/fact_home/yishi` | Ceph, `rw,relatime` | 30T total / 19T used / 11T free | ~800G | source/config/small manifests only |
| `/fact_data/yishi` | Ceph, `rw,relatime` | 66T / 49T / 17T free | ~15G | authoritative retained evidence |
| `/scratch/yishi` | Ceph, `rw,relatime` | 68T / 35T / 33T free | ~8.5G before model copy | regenerable envs/caches/work copies |

User quota is `UNKNOWN`: `quota -s -u yishi` cannot obtain file descriptors for
the container/Ceph mountpoints, `xfs_quota` reports “No such device or address”,
and `ceph` cannot authenticate without a cluster keyring. Filesystem free space
is therefore not treated as a user quota.

The legacy `/fact_home/yishi/agent-checkpoint` was not moved, overwritten, or
deleted. Read-only `du` classified its largest roots as:

- `results/experiment1`: 657,676,247,552 bytes — checkpoint, disk, evaluator,
  trajectory and experiment evidence;
- `firecracker-test`: 25,307,983,872 bytes — Firecracker `memory.snap`, restore
  snapshots, rootfs and mutation artifacts;
- `results/semantic_capture`: 13,584,962,560 bytes — native capture/mapping and
  snapshot evidence;
- `results/provenance_framework`: 4,624,615,936 bytes — provenance evidence.

The fixed model source is ~57G under another user’s HOME path. A single-writer
copy (Slurm jobs 1698646 and 1698710) placed it under
`/scratch/yishi/stage1-model/Qwen3-Coder-30B-A3B-Instruct`; relative file/size
and then per-file SHA-256 manifests matched. Its revision remains
`UNRESOLVED_LOCAL_SOURCE`; the scratch copy is not treated as irreplaceable
evidence. Copy logs and manifests were staged and published with `VERIFIED`
receipts under FACT_DATA.

The first vLLM 0.10.1 scratch install (job 1698012) timed out at 01:30:00 while
downloading/resolving dependencies and has been retained as `INVALID_INFRA`.
No READY marker or compatibility result was produced. A distinct direct-wheel
install (job 1698764) is still subject to its own bounded timeout and has not
been treated as a compatibility result.

Authoritative machine-readable records:

- `/fact_data/yishi/agent-checkpoint-stage1/manifests/storage-audit-20261008/`
- `/fact_data/yishi/agent-checkpoint-stage1/manifests/storage-tree-20261008/`
- `/fact_data/yishi/agent-checkpoint-stage1/manifests/storage_manifest_20261008/`
- `/fact_data/yishi/agent-checkpoint-stage1/runs/pilot/vllm/invalid-infra-1698012/`

Each published directory has a `_storage_publish_receipt.json` with status
`VERIFIED`; scratch sources are preserved. No old result was migrated.
