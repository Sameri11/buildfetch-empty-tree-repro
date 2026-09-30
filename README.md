# Cache never serves an action result whose output directory contains an empty file

A Bazel action that writes a **0-byte file inside an output directory** never gets a remote cache hit. Bazel uploads the result and the server answers `UpdateActionResult` with OK, but a later `GetActionResult` for the same action returns `NOT_FOUND`. With 1 byte in the file instead, the action is served from the cache as expected.

## Run

Requires [Bazelisk](https://github.com/bazelbuild/bazelisk) (installed as `bazel`); `.bazelversion` pins Bazel 9.2.0.

```sh
REMOTE_CACHE=<cache_url> \
REMOTE_INSTANCE_NAME=<instance name> \
REMOTE_TOKEN=<token with write access> \
./repro.sh
```

The script:

1. Builds two targets that differ only in the size of the one file each writes into its output directory. Every run uses fresh action keys, so both actions execute locally and upload.
2. Runs `bazel clean --expunge`, which removes all local outputs and caches.
3. Builds each target again. Both should be remote cache hits.

### On GitHub Actions

Add repository secrets `REMOTE_CACHE`, `REMOTE_INSTANCE_NAME` and `REMOTE_TOKEN`. Every push, or a manual run from the **Actions** tab, then runs `repro.sh` on `ubuntu-latest` (`.github/workflows/repro.yml`). The job fails while the bug is present. The output is shown in the run summary, and the gRPC logs are attached as the `grpc-logs` artifact.

## Result

```
== 1. Build both targets: each action runs locally and uploads its result
3 processes: 1 internal, 2 darwin-sandbox.
== 2. bazel clean --expunge (drop every local output and local cache)
== 3. Build each target again: both should be remote cache hits
//:dir_with_empty_file     MISS (executed again)  2 processes: 1 internal, 1 darwin-sandbox.
//:dir_with_one_byte_file  HIT                    2 processes: 1 remote cache hit, 1 internal.
```

This was produced on macOS against `cache.eu-central-a.buildfetch.com` on 2026-09-30. Linux CI runners give the same result. The script exits with status 1 while the bug is present.

Control: the same script against [bazel-remote](https://github.com/buchgr/bazel-remote) 2.6.2 (`--grpc_address localhost:9092`, "gRPC AC dependency checks: enabled") reports **HIT** for both targets and exits 0:

```sh
REMOTE_CACHE=grpc://localhost:9092 REMOTE_INSTANCE_NAME=repro ./repro.sh
```

`logs/` holds Bazel's `--remote_grpc_log` for each build: every cache call with its status. For `//:dir_with_empty_file`, build 1 records `UpdateActionResult` → OK, and step 3 records `GetActionResult` → `NOT_FOUND` for the same action digest.

## Expected behaviour (REAPI v2)

[`remote_execution.proto`, lines 342-344](https://github.com/bazelbuild/remote-apis/blob/adbf4a27c86fbea4a37637a6cbcacef372406fe7/build/bazel/remote/execution/v2/remote_execution.proto#L342-L344):

> Servers MUST behave as though empty blobs are always available, even if they have not been uploaded. Clients MAY optimize away the uploading or downloading of empty blobs.

Bazel does not upload the empty blob, which this rule allows. `GetActionResult` ([lines 160-169](https://github.com/bazelbuild/remote-apis/blob/adbf4a27c86fbea4a37637a6cbcacef372406fe7/build/bazel/remote/execution/v2/remote_execution.proto#L160-L169)) may check that blobs referenced by the result exist, but the empty blob always counts as present.

## Also observed

- `FindMissingBlobs` for the empty digest (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855/0`) reports it as present.
- Uploading the empty blob explicitly before `UpdateActionResult` does not help.
- A 0-byte file as a top-level output (`output_files`) is served correctly. Only files inside an output directory's `Tree` are affected, and their names don't matter.
