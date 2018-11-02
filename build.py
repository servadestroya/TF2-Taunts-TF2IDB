#!/usr/bin/env python3
import argparse
import buildtools.libpy.tony_updater as updater
import buildtools.libpy.versioning as versioning
import buildtools.libpy.spcomp as spcomp
import buildtools.libpy.vdf as vdf
from pathlib import Path
from typing import List, Tuple, Callable, Iterable, Optional, Type, Union, NamedTuple, Dict
import shutil
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(f"Project builder for {TauntsPluginProject.project_name}")
    parser.add_argument("--smlib", help="Path to the SourceMod scripting directory", type=Path, required=True)
    parser.add_argument("--item_schema_api", help="Item schema API to build the plugin for", type=str,
                        choices=TauntsPluginProject.project_flavours.keys(), required=True)
    parser.add_argument("--branch", help="Name of the branch this release is targeting"
                                         "(useful when working with a detached HEAD)", type=str)
    args = parser.parse_args()
    smlib: Path = args.smlib / "include"
    flavour: str = args.item_schema_api
    branch: Optional[str] = getattr(args, "branch", None)

    compiler = spcomp.get_compiler_from_include(smlib)
    if compiler is None:
        parser.exit(1, message=f"{parser.prog}: SourceMod library does not contain a valid compiler")

    build(item_schema_api=flavour,
          project_root=Path(__file__).parent,
          package_dir=Path.cwd() / f"build-{flavour}",
          compiler=compiler,
          smlib=smlib,
          branch=branch)

    return 0


def build(item_schema_api: str,
          project_root: Path,
          package_dir: Path,
          compiler: Path,
          smlib: Path,
          branch: Optional[str] = None) -> None:
    if item_schema_api not in TauntsPluginProject.project_flavours.keys():
        raise ValueError(f"{item_schema_api} is not a valid build flavour")

    package_root = package_dir / "root"
    project = TauntsPluginProject(project_root,
                                  build_type=TauntsPluginProject.PackageBuild)
    project_as_dev = TauntsPluginProject(project_root,
                                         build_type=TauntsPluginProject.DevBuild)
    version_info = versioning.get_version_from_git(project.root)
    if branch is not None and len(branch) > 0:
        version_info = versioning.VersionInfo(version_info.tag,
                                              version_info.commit_number,
                                              branch)

    project_on_package = TauntsPluginProject(package_root,
                                             build_type=TauntsPluginProject.PackageBuild)
    project_updater = ProjectUpdater(version_info.branch, item_schema_api)

    # Creating package root
    copy_dirs: List[Tuple[Path, Path]] = [
        (project.dir_scripting, project_on_package.dir_scripting),
        (project.dir_translations, project_on_package.dir_translations),
        (project.dir_gamedata, project_on_package.dir_gamedata)
    ]
    if package_dir.exists():
        shutil.rmtree(str(package_dir))
    project_on_package.root.mkdir(parents=True)
    for on_repo, on_package in copy_dirs:
        shutil.copytree(str(on_repo), str(on_package),
                        # Ignore temp includes that might have been created in previous dev builds
                        ignore=ignore_on_parent_path(project_as_dev.dir_temp_includes))
    project_on_package.dir_plugins.mkdir()

    # Making temp includes
    for temp_include, contents in (
            (project_on_package.file_include_updater, updater.make_include(project_updater.get_url())),
            (project_on_package.file_include_version, versioning.make_include(version_info, "__untagged__"))
    ):
        if temp_include.exists():
            raise FileExistsError(f"Package file conflicts with temporary include: '{temp_include}'")
        with open(str(temp_include), "w") as temp_file:
            temp_file.write(contents)

    # Compiling

    define = TauntsPluginProject.project_flavours[item_schema_api]
    result = subprocess.run([str(compiler),
                             # These must be absolute since we change directory to
                             # ``project_package.dir_plugins``, thus relative paths
                             # won't resolve correctly
                             str(project_on_package.file_main_source.absolute()),
                             f"-i={smlib.absolute()}",
                             f"-i={project_on_package.dir_include.absolute()}",
                             f"-i={project_on_package.dir_temp_includes.absolute()}",
                             f"-D={project_on_package.dir_plugins.absolute()}"] +
                            ([f"{define}="] if define is not None else []))
    result.check_returncode()

    # Packing files

    archive_path = package_dir / f"{TauntsPluginProject.project_name}" \
                                 f"-n{version_info.commit_number}-{item_schema_api}.zip"
    shutil.make_archive(str(archive_path.absolute()).rsplit(".", 1)[0],
                        str(archive_path.absolute()).rsplit(".", 1)[1],
                        str(package_root.absolute()))

    # Creating updater manifest

    version_str = f"{version_info.tag}.{version_info.commit_number}-{item_schema_api}"
    project_url = f"https://github.com/{project_updater.user}/TF2-Taunts-TF2IDB"
    manifest_data = updater.build_vdf(package_root,
                                      (f"Version {version_str} is out!", f"Go to {project_url} to see the changes"),
                                      version_str)
    with open(str(package_root / project_updater.manifest_name), "w") as updater_manifest:
        vdf.dump(manifest_data, updater_manifest, pretty=True)
    pass


class GitHubUpdaterData:
    def __init__(self, user: str, repo: str, branch: str, project_path: str,
                 manifest_name: str = "updater.txt"):
        self.user: str = user
        self.repo: str = repo
        self.branch: str = branch
        self.project_path: str = project_path
        self.manifest_name: str = manifest_name

    def get_url(self) -> str:
        return f"https://raw.githubusercontent.com/" \
               f"{self.user}/{self.repo}/{self.branch}/{self.project_path}/{self.manifest_name}"


class SMProject:
    class PackageBuild:
        pass

    class DevBuild:
        pass

    BuildTypes = Union[Type[PackageBuild], Type[DevBuild]]

    def __init__(self, project_root: Path, project_name: str, build_type: BuildTypes):
        self.root: Path = project_root
        self.name: str = project_name
        self.build_type = build_type

    @property
    def dir_buildtools(self) -> Path:
        return self.root / "buildtools"

    @property
    def dir_scripting(self) -> Path:
        return self.root / "scripting"

    @property
    def dir_include(self) -> Path:
        return self.dir_scripting / "include"

    @property
    def dir_plugins(self) -> Path:
        return self.root / "plugins"

    @property
    def dir_translations(self) -> Path:
        return self.root / "translations"

    @property
    def dir_gamedata(self) -> Path:
        return self.root / "gamedata"

    @property
    def dir_project_include(self) -> Path:
        return self.dir_include / self.name

    @property
    def dir_temp_includes(self):
        return self.dir_include if self.build_type is SMProject.PackageBuild else \
               self.dir_include / ".tmp"

    @property
    def dir_temp_project_includes(self):
        return self.dir_temp_includes / self.name


class TauntsPluginProject(SMProject):
    project_flavours: Dict[str, Optional[str]] = {
        "tf2idb": None,
        "tf2ii":  "_USE_TF2II_INSTEAD_OF_TF2IDB"
    }
    project_name: str = "tf2_taunts_tf2idb"

    def __init__(self, project_root: Path, build_type: SMProject.BuildTypes):
        super().__init__(project_root, TauntsPluginProject.project_name, build_type)

    @staticmethod
    def get_flavour_by_definitions(defines: Iterable[str]) -> str:
        defines = list(defines)
        flavours = TauntsPluginProject.project_flavours
        default_flavour: str
        for flavour, define in flavours.items():
            if define is not None and define in defines:
                return flavour
            if define is None:
                default_flavour = flavour
        else:
            assert default_flavour is not None
            return default_flavour

    @property
    def file_main_source(self) -> Path:
        return self.dir_scripting / f"{self.project_name}.sp"

    @property
    def file_include_version(self) -> Path:
        return self.dir_temp_project_includes / "autoversioning.inc"

    @property
    def file_include_updater(self) -> Path:
        return self.dir_temp_project_includes / "updater_helpers.inc"


class ProjectUpdater(GitHubUpdaterData):
    def __init__(self, local_branch: Optional[str], schema_api: str):
        branch: Optional[str] = ProjectUpdater.format_updater_branch(local_branch)
        super().__init__(user="fakuivan",
                         repo="sm_updater_plugins",
                         branch=branch if branch is not None else "__updater_disabled__",
                         project_path=f"{TauntsPluginProject.project_name}-{schema_api}")

    @staticmethod
    def format_updater_branch(active_branch: str) -> Optional[str]:
        return {
            "updater":          "master",
            "updater_test":     "test",
            "dev":              "dev"
        }.get(active_branch, None)


def ignore_on_parent_path(parent: Path) -> Callable[[str, List[str]], Iterable[str]]:
    def which_paths_are_on_parent(path: str, names: List[str]):
        ignored: List[str] = list()
        path: Path = Path(path)
        for name in names:
            path_name: Path = path / name
            if parent in path_name.parents or parent.samefile(path_name):
                ignored += [name]
        return set(ignored)
    return which_paths_are_on_parent


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
