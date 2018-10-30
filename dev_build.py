#!/usr/bin/env python3
import argparse
import sys
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional
from build import TauntsPluginProject, ProjectUpdater
import buildtools.libpy.spcomp as spcomp
import buildtools.libpy.tony_updater as updater
import buildtools.libpy.versioning as versioning


def main() -> int:
    arguments = sys.argv[1:]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-i", type=Path, action='append')
    args_namespace = parser.parse_known_args(args=arguments)[0]
    parsed_include_dirs: Optional[List[Path]] = getattr(args_namespace, "i")
    if parsed_include_dirs is None:
        raise ValueError("At least one include path must be provided")
    include_dirs: List[Path] = parsed_include_dirs
    compiler: Optional[Path]

    for _dir in include_dirs:
        compiler = spcomp.get_compiler_from_include(_dir)
        if compiler is not None:
            break
    else:
        raise FileNotFoundError("Failed to find compiler executable based on included paths")

    # What if the user passes "_USE_TF2II_INSTEAD_OF_TF2IDB=0"?
    schema_api = TauntsPluginProject.get_flavour_by_definitions(
        (define[:-1] for define in arguments if define[-1] == "=")
    )
    project_data = TauntsPluginProject(Path(__file__).parent, build_type=TauntsPluginProject.DevBuild)
    version_info = versioning.get_version_from_git(project_data.root)
    updater_data = ProjectUpdater(version_info.branch, schema_api)

    if project_data.dir_temp_project_includes.exists():
        shutil.rmtree(str(project_data.dir_temp_project_includes))
    project_data.dir_temp_project_includes.mkdir(parents=True)

    with open(str(project_data.file_include_updater), "w") as updater_include:
        updater_include.write(updater.make_include(updater_data.get_url()))

    with open(str(project_data.file_include_version), "w") as version_include:
        version_include.write(versioning.make_include(version_info, "__untagged__"))

    result = subprocess.run([str(compiler)] + arguments + [f"-i={project_data.dir_temp_includes}"])

    return result.returncode


if __name__ == "__main__":
    handler = spcomp.SpcompExceptionHandler("Build preparation error")
    handler.activate()
    import sys as _sys
    _sys.exit(main())
