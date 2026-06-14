from pathlib import Path
from shutil import copyfile

Import("env")


def copy_uf2(target, source, env):
    project_dir = Path(env["PROJECT_DIR"])
    uf2_path = Path(env.subst("$BUILD_DIR")) / f"{env.subst('$PROGNAME')}.uf2"
    output_path = project_dir / "rp2040-cdc-2port-dmx.uf2"
    copyfile(uf2_path, output_path)
    print(f"Copied {uf2_path} -> {output_path}")


env.AddPostAction("$BUILD_DIR/${PROGNAME}.uf2", copy_uf2)
env.AddPostAction("checkprogsize", copy_uf2)
