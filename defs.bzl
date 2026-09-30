"""One action that writes a file with the given content into an output directory (tree artifact)."""

def _dir_with_file_impl(ctx):
    out = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.run_shell(
        outputs = [out],
        arguments = [ctx.attr.content, out.path + "/file"],
        command = "printf '%s' \"$1\" > \"$2\"",
        # Picks up --action_env=REPRO_SALT, so each repro.sh run gets fresh action keys.
        use_default_shell_env = True,
    )
    return [DefaultInfo(files = depset([out]))]

dir_with_file = rule(
    implementation = _dir_with_file_impl,
    attrs = {"content": attr.string()},
)
