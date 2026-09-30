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

Two workflows run on every push, or by hand from the **Actions** tab, both on `ubuntu-latest`. Each shows the `repro.sh` output in the run summary and attaches the gRPC logs as an artifact.

| Workflow | Cache | Expected |
|---|---|---|
| `Repro` (`.github/workflows/repro.yml`) | From repository secrets `REMOTE_CACHE`, `REMOTE_INSTANCE_NAME`, `REMOTE_TOKEN` | Fails while the bug is present |
| `Reference (bazel-remote)` (`.github/workflows/reference-bazel-remote.yml`) | [bazel-remote](https://github.com/buchgr/bazel-remote) 2.6.2 started on the runner; no secrets | Passes: both targets are HITs |

## Result

Final lines of `repro.sh`:

```
== Result
//:dir_with_empty_file     MISS (executed again)  2 processes: 1 internal, 1 darwin-sandbox.
//:dir_with_one_byte_file  HIT                    2 processes: 1 remote cache hit, 1 internal.
```

Each build is run with `--remote_grpc_log`, and `grpclog.py` prints every cache call Bazel made, with the status the server returned (Python 3, no dependencies). Trimmed:

```
== 1. Build both targets: each action runs locally and uploads its result
  bazel-bin/dir_with_empty_file/file: 0 bytes
    //:dir_with_empty_file
      GetActionResult     NOT_FOUND  action 8ffecd31…cde5/145
      FindMissingBlobs    OK         asked about 1d46da9b…a205/80 (Tree), 9c619abd…314d/235 (Command), 8ffecd31…cde5/145 (Action), e3b0c442…b855/0; 2 missing
      Write               OK         uploaded 9c619abd…314d/235
      Write               OK         uploaded 8ffecd31…cde5/145
      UpdateActionResult  OK         action 8ffecd31…cde5/145; output dir bazel-out/…/dir_with_empty_file -> Tree 1d46da9b…a205/80
== 3. Build each target again: both should be remote cache hits
    //:dir_with_empty_file
      GetActionResult     NOT_FOUND  action 8ffecd31…cde5/145
      FindMissingBlobs    OK         asked about 8ffecd31…cde5/145, 1d46da9b…a205/80, 9c619abd…314d/235, e3b0c442…b855/0; 0 missing
      UpdateActionResult  OK         action 8ffecd31…cde5/145; output dir bazel-out/…/dir_with_empty_file -> Tree 1d46da9b…a205/80
    //:dir_with_one_byte_file
      GetActionResult     OK         action d761f627…cbac/145; output dir bazel-out/…/dir_with_one_byte_file -> Tree 5cd1bd80…f638/82
      Read                OK         downloaded 5cd1bd80…f638/82
      Read                OK         downloaded 2d711642…4881/1
```

Step 1: the server accepts the result with `UpdateActionResult` → OK. Step 3: `GetActionResult` for the same action digest returns `NOT_FOUND`, although `FindMissingBlobs` says every blob it references is present (`0 missing`), the empty blob included. Bazel then runs the action again and uploads the same result again, also accepted with OK. The 1-byte control is served and downloaded.

This was produced on macOS against `cache.eu-central-a.buildfetch.com` on 2026-09-30. The script exits with status 1 while the bug is present. Raw logs are kept in `logs/`.

Control: the same script against bazel-remote 2.6.2 (with "gRPC AC dependency checks: enabled") reports **HIT** for both targets and exits 0. For the empty-file target, `GetActionResult` returns OK and Bazel downloads the Tree. It does not download the empty file, which the spec allows:

```sh
REMOTE_CACHE=grpc://localhost:9092 REMOTE_INSTANCE_NAME=repro ./repro.sh
```

```
    //:dir_with_empty_file
      GetActionResult     OK         action 50c5d462…c180/145; output dir bazel-out/…/dir_with_empty_file -> Tree 1d46da9b…a205/80
      Read                OK         downloaded 1d46da9b…a205/80
```

## Expected behaviour (REAPI v2)

[`remote_execution.proto`, lines 342-344](https://github.com/bazelbuild/remote-apis/blob/adbf4a27c86fbea4a37637a6cbcacef372406fe7/build/bazel/remote/execution/v2/remote_execution.proto#L342-L344):

> Servers MUST behave as though empty blobs are always available, even if they have not been uploaded. Clients MAY optimize away the uploading or downloading of empty blobs.

Bazel does not upload the empty blob, which this rule allows. `GetActionResult` ([lines 160-169](https://github.com/bazelbuild/remote-apis/blob/adbf4a27c86fbea4a37637a6cbcacef372406fe7/build/bazel/remote/execution/v2/remote_execution.proto#L160-L169)) may check that blobs referenced by the result exist, but the empty blob always counts as present.

## Also observed

- `FindMissingBlobs` for the empty digest (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855/0`) reports it as present.
- Uploading the empty blob explicitly before `UpdateActionResult` does not help.
- A 0-byte file as a top-level output (`output_files`) is served correctly. Only files inside an output directory's `Tree` are affected, and their names don't matter.
