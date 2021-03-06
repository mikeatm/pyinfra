# pyinfra
# File: pyinfra/modules/apt.py
# Desc: manage apt packages & repositories

'''
Manage apt packages and repositories.
'''

from urlparse import urlparse
from datetime import timedelta

from pyinfra.api import operation, OperationException
from pyinfra.facts.apt import parse_apt_repo

from . import files


@operation
def key(state, host, key):
    '''
    Add apt gpg keys with ``apt-key``.

    + key: filename or URL

    Note:
        always returns an add command, not state checking
    '''

    if urlparse(key).scheme:
        return ['apt-key adv --fetch-keys {0}'.format(key)]

    return ['apt-key add {0}'.format(key)]


@operation
def repo(state, host, name, present=True):
    '''
    Manage apt repositories.

    + name: apt line, repo url or PPA
    + present: whether the repo should exist on the system
    '''

    commands = []

    apt_sources = host.apt_sources or {}

    # Parse out the URL from the name if available
    repo = parse_apt_repo(name)
    if repo:
        name, _ = repo

    # Convert ppa's to full URLs
    elif name.startswith('ppa:'):
        name = 'http://ppa.launchpad.net/{0}/ubuntu'.format(name[4:])

    is_present = name in apt_sources

    # Doesn't exit and we want it
    if not is_present and present:
        commands.append('apt-add-repository "{0}" -y'.format(name))

    # Exists and we don't want it
    if is_present and not present:
        commands.append('apt-add-repository "{0}" -y --remove'.format(name))

    return commands


@operation
def deb(state, host, source, present=True):
    '''
    Install/manage ``.deb`` file packages.

    + source: filename or URL of the ``.deb`` file
    + present: whether or not the package should exist on the system

    Note:
        when installing, ``apt-get install -f`` will be run to install any unmet
        dependencies

    URL sources with ``present=False``:
        if the ``.deb`` file isn't downloaded, pyinfra can't remove any existing package
        as the file won't exist until mid-deploy
    '''

    commands = []

    # If source is a url
    if urlparse(source).scheme:
        # Generate a temp filename
        temp_filename = state.get_temp_filename(source)

        # Ensure it's downloaded
        commands.extend(files.download(source, temp_filename))

        # Override the source with the downloaded file
        source = temp_filename

    # Check for file .deb information (if file is present)
    info = host.deb_package(source)

    exists = False

    # We have deb info! Check against installed packages
    if info:
        current_packages = host.deb_packages

        if (
            info['name'] in current_packages
            and current_packages[info['name']] == info['version']
        ):
            exists = True

    # Package does not exist and we want?
    if present and not exists:
        commands.extend([
            # Install .deb file - ignoring failure (on unmet dependencies)
            'DEBIAN_FRONTEND=noninteractive dpkg -i {0} || true'.format(source),
            # Attempt to install any missing dependencies
            'DEBIAN_FRONTEND=noninteractive apt-get install -fy',
            # Now reinstall, and critically configure, the package - if there are still
            # missing deps, now we error
            'DEBIAN_FRONTEND=noninteractive dpkg -i {0}'.format(source)
        ])

    # Package exists but we don't want?
    if exists and not present:
        commands.extend([
            'DEBIAN_FRONTEND=noninteractive apt-get remove {0} -y'.format(info['name'])
        ])

    return commands


@operation
def packages(
    state, host,
    packages=None, present=True, update=False, cache_time=None, upgrade=False
):
    '''
    Install/remove/upgrade packages & update apt.

    + packages: list of packages to ensure
    + present: whether the packages should be installed
    + update: run apt update
    + cache_time: when used with update, cache for this many seconds
    + upgrade: run apt upgrade

    Note:
        ``cache_time`` only works on systems that provide the
        ``/var/lib/apt/periodic/update-success-stamp`` file (ie Ubuntu).
    '''

    if packages is None:
        packages = []

    if isinstance(packages, basestring):
        packages = [packages]

    # apt packages are case-insensitive
    packages = [package.lower() for package in packages]

    commands = []

    # If cache_time check when apt was last updated, prevent updates if within time
    if cache_time:
        # Ubuntu provides this handy file
        cache_info = host.file('/var/lib/apt/periodic/update-success-stamp')

        # Time on files is not tz-aware, and will be the same tz as the server's time,
        # so we can safely remove the tzinfo from host.date before comparison.
        cache_time = host.date.replace(tzinfo=None) - timedelta(seconds=cache_time)
        if cache_info and cache_info['mtime'] and cache_info['mtime'] > cache_time:
            update = False

    if update:
        commands.append('apt-get update')

    if upgrade:
        commands.append('DEBIAN_FRONTEND=noninteractive apt-get upgrade -y')

    current_packages = host.deb_packages

    # Raise error if apt isn't installed as it's a system package manager
    if current_packages is None:
        raise OperationException('apt is not present on {0}'.format(host.ssh_hostname))

    if present is True:
        # Packages specified but not installed
        diff_packages = [
            package for package in packages
            if package not in current_packages
        ]

        if diff_packages:
            commands.append(
                'DEBIAN_FRONTEND=noninteractive apt-get install -y {0}'.format(
                    ' '.join(diff_packages)
                )
            )

    else:
        # Packages specified & installed
        diff_packages = [
            package for package in packages
            if package in current_packages
        ]

        if diff_packages:
            commands.append(
                'DEBIAN_FRONTEND=noninteractive apt-get remove -y {0}'.format(
                    ' '.join(diff_packages)
                )
            )

    return commands
