#!/usr/bin/env python3
"""Prints the remote cache calls in a Bazel --remote_grpc_log file, grouped by target.

The file is a stream of varint-length-prefixed LogEntry messages, defined in
https://github.com/bazelbuild/bazel/blob/9.2.0/src/main/protobuf/remote_execution_log.proto
It is decoded with a minimal protobuf reader so no dependencies are needed.
"""

import sys

STATUS = {0: "OK", 3: "INVALID_ARGUMENT", 5: "NOT_FOUND", 8: "RESOURCE_EXHAUSTED", 9: "FAILED_PRECONDITION"}


def varint(data, i):
    n = shift = 0
    while True:
        byte = data[i]
        i += 1
        n |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return n, i


def fields(data):
    """{field number: [values]}; nested messages and strings stay bytes."""
    i, out = 0, {}
    while i < len(data):
        key, i = varint(data, i)
        wire = key & 7
        if wire == 0:
            value, i = varint(data, i)
        elif wire == 2:
            size, i = varint(data, i)
            value, i = data[i:i + size], i + size
        else:
            size = 8 if wire == 1 else 4
            value, i = data[i:i + size], i + size
        out.setdefault(key >> 3, []).append(value)
    return out


def one(msg, number, default=b""):
    return msg.get(number, [default])[0]


def digest(data):
    """build.bazel.remote.execution.v2.Digest: hash=1, size_bytes=2."""
    d = fields(data)
    return f"{one(d, 1).decode()}/{one(d, 2, 0)}"


def output_dirs(action_result):
    """ActionResult.output_directories=3; OutputDirectory: path=1, tree_digest=3."""
    dirs = [fields(d) for d in fields(action_result).get(3, [])]
    return "; ".join(f"output dir {one(d, 1).decode()} -> Tree {digest(one(d, 3))}" for d in dirs)


def describe(method, details, status):
    """RpcCallDetails: read=5, write=6, get_action_result=8, find_missing_blobs=10, update_action_result=13."""
    if method == "GetActionResult":
        d = fields(one(details, 8))
        action = digest(one(fields(one(d, 1)), 2))  # GetActionResultRequest.action_digest=2
        return f"action {action}" + (f"; {output_dirs(one(d, 2))}" if status == 0 else "")
    if method == "UpdateActionResult":
        d = fields(one(details, 13))
        request = fields(one(d, 1))  # UpdateActionResultRequest: action_digest=2, action_result=3
        return f"action {digest(one(request, 2))}; {output_dirs(one(request, 3))}"
    if method == "FindMissingBlobs":
        d = fields(one(details, 10))
        asked = [digest(b) for b in fields(one(d, 1)).get(2, [])]  # blob_digests=2
        missing = fields(one(d, 2)).get(2, [])  # missing_blob_digests=2
        return f"asked about {', '.join(asked)}; {len(missing)} missing"
    if method == "Write":
        names = fields(one(details, 6)).get(1, [])  # resource_names=1
        return "uploaded " + ", ".join("/".join(n.decode().split("/")[-2:]) for n in names)
    if method == "Read":
        name = one(fields(one(fields(one(details, 5)), 1)), 1).decode()  # ReadRequest.resource_name=1
        return "downloaded " + "/".join(name.split("/")[-2:])
    return ""


def main(path):
    data, i, by_target = open(path, "rb").read(), 0, {}
    while i < len(data):
        size, i = varint(data, i)
        entry, i = fields(data[i:i + size]), i + size
        # LogEntry: metadata=1, status=2, method_name=3, details=4. RequestMetadata.target_id=6.
        target = one(fields(one(entry, 1)), 6).decode()
        if not target:
            continue  # GetCapabilities
        method = one(entry, 3).decode().rsplit("/", 1)[-1]
        status = one(fields(one(entry, 2)), 1, 0)
        by_target.setdefault(target, []).append(
            f"      {method:<19} {STATUS.get(status, status):<10} {describe(method, fields(one(entry, 4)), status)}",
        )
    for target, lines in sorted(by_target.items()):
        print(f"    {target}")
        print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
