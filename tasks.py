import sys
import psutil
import json
import os
import subprocess
import shutil
from pathlib import Path
from glob import glob

from invoke import task
import github
from galaxy.tools import zip_folder_to_file


with open('src/manifest.json') as f:
    __version__ = json.load(f)['version']


REQUIREMENTS = os.path.join('requirements.txt')
REQUIREMENTS_DEV = os.path.join('requirements-dev')

GALAXY_PATH = ''
DIST_DIR = ''
GALAXY_PYTHONPATH = ''

if sys.platform == 'win32':
    GALAXY_PATH = 'C:\\Program Files (x86)\\GOG Galaxy\\GalaxyClient.exe'
    DIST_DIR = os.environ['localappdata'] + '\\GOG.com\\Galaxy\\plugins\\installed'
    PYTHON = 'python'
    GALAXY_PYTHONPATH = str(Path(os.path.expandvars("%programfiles(x86)%")) / "GOG Galaxy" / "python" / "python.exe")
elif sys.platform == 'darwin':
    GALAXY_PATH = "/Applications/GOG Galaxy.app/Contents/MacOS/GOG Galaxy"
    DIST_DIR = os.environ['HOME'] + r"/Library/Application\ Support/GOG.com/Galaxy/plugins/installed"
    PYTHON = 'python3'

DIST_PLUGIN = os.path.join(DIST_DIR, 'humblebundle')
THIRD_PARTY_RELATIVE_DEST = 'modules'


@task
def install(c, dev=False):
    req = REQUIREMENTS_DEV if dev else REQUIREMENTS
    c.run(f"{PYTHON} -m pip install -r {req}")


@task
def build(c, output=DIST_PLUGIN):
    output = Path(output).resolve()

    print('removing', output)
    if os.path.exists(output):
        shutil.rmtree(output)

    print('copying source code to ', str(output))
    shutil.copytree('src', output, ignore=shutil.ignore_patterns(
        '__pycache__', '.mypy_cache', 'galaxy'))

    args = [
        PYTHON, "-m", "pip", "install",
        "-r", REQUIREMENTS,
        "--target", str(output / THIRD_PARTY_RELATIVE_DEST),
        # "--implementation", "cp",
        # "--python-version", "37",
        # "--no-deps"
    ]
    print(f'running `{" ".join(args)}`')
    subprocess.check_call(args)


@task
def dist(c, output=DIST_PLUGIN, galaxy_path=GALAXY_PATH, no_deps=False):
    for proc in psutil.process_iter(attrs=['exe'], ad_value=''):
        if proc.info['exe'] == galaxy_path:
            print(f'Galaxy at {galaxy_path} is running!. Terminating...')
            proc.terminate()
            break
    else:
        print('Galaxy instance not found.')

    if no_deps:
        c.run(f'inv copy -o {output}')
    else:
        c.run(f'inv build -o {output}')

    print(f'Reopening Galaxy from {galaxy_path}')
    subprocess.run([galaxy_path])


@task
def debug(c, output=DIST_PLUGIN, deps=False):
    this_plugin = 'plugin-humble'
    for proc in psutil.process_iter(attrs=['exe'], ad_value=''):
        if proc.info['exe'] == GALAXY_PYTHONPATH:
            if this_plugin in proc.cmdline()[-1]:
                print(f'Running plugin instance found!. Terminating...')
                proc.terminate()
                break
    if not deps:
        c.run(f'inv copy -o {output}')
    else:
        c.run(f'inv build -o {output}')
    print("Now, click 'retry' for crashed plugin in Settings")


@task
def copy(c, output=DIST_PLUGIN, galaxy_path=GALAXY_PATH):
    print('copying source code ...')
    for file_ in glob("src/*.py"):
        shutil.copy(file_, output)
    for file_ in glob("src/local/*.py"):
        shutil.copy(file_, Path(output) / 'local')
    for file_ in glob("src/*.ini"):
        shutil.copy(file_, output)


@task
def test(c, target=None):

    if target is not None:
        config = str(Path(__file__).parent / 'pytest-build.ini')
        with open(config, 'w') as f:
            f.write("[pytest]\n")
            f.write(f"python_paths = {target}")  # pytest-pythonpaths required
    else:
        config = 'pytest.ini'

    c.run(f"{PYTHON} -m pytest -c {config} -vv tests/common src --color=yes")
    if sys.platform == 'win32':
        c.run(f"{PYTHON} -m pytest tests/windows")

    if target:
        modules = ['local', 'model', 'plugin.py', 'consts.py', 'humbledownloader.py', 'webservice.py', 'settings.py', 'library.py']
        os.environ['MYPYPATH'] = str(Path(target) / THIRD_PARTY_RELATIVE_DEST)
        modules_full_path = [str(Path(target) / mod) for mod in modules]
        print(f'running mypy check for {str(Path(target))} directory')
        c.run(f"{PYTHON} -m mypy {' '.join(modules_full_path)} --follow-imports silent")
        print('done')


@task
def archive(c, zip_name=None, target=None):
    if zip_name is None:
        zip_name = f'humblebundle_{__version__}.zip'

    zip_folder_to_file(target, zip_name)
    return zip_name


@task
def release(c, full=None):
    print('New release version will be: ', __version__, '. is it OK?')
    if input('y/n').lower() != 'y':
        return

    g = github.Github('UncleGoogle', input('personal token: '))
    repo = g.get_repo('UncleGoogle/galaxy-integration-humblebundle')

    if full:
        print('running tests')
        build(c, output='build')
        test(c, target='build')
        asset_path = archive(c, target='build')
        print(asset_path)

    # TODO check if release already is therek
    # if not:

    tag = 'v' + __version__
    print('creating and pushing to origin tag: ', tag)
    # c.run(f'git tag {tag}')
    # c.run(f'git push origin {tag}')

    print('creating github draft release')
    release = repo.create_git_release(
        tag=tag,
        name=__version__,
        message="draft",
        draft=True
    )

    #------

    if full:
        print('uploading assets')
        release.upload_asset(asset_path, label='', content_type= , name=)
