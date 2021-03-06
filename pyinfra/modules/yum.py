# pyinfra
# File: pyinfra/modules/yum.py
# Desc: manage yum packages & repositories

'''
Manage yum packages and repositories. Note that yum package names are case-sensitive.
'''

from urlparse import urlparse
from cStringIO import StringIO

from pyinfra.api import operation, OperationException

from . import files


@operation
def key(state, host, key):
    '''
    Add yum gpg keys with ``rpm``.

    + key: filename or URL

    Note:
        always returns one command, not state checking
    '''

    return ['rpm --import {0}'.format(key)]


@operation
def repo(state, host, name, baseurl, present=True, description=None, gpgcheck=True):
    '''
    Manage yum repositories.

    + name: filename for the repo (in ``/etc/yum/repos.d/``)
    + baseurl: the baseurl of the repo
    + present: whether the ``.repo`` file should be present
    + description: optional verbose description
    + gpgcheck: whether set ``gpgcheck=1``
    '''

    filename = '/etc/yum.repos.d/{0}.repo'.format(name)

    # If we don't want the repo, just remove any existing file
    if not present:
        return files.file(state, host, filename, present=False)

    # Build the repo file from string
    repo = '''
[{name}]
name={description}
baseurl={baseurl}
gpgcheck={gpgcheck}
'''.format(
        name=name, baseurl=baseurl, description=description,
        gpgcheck=1 if gpgcheck else 0
    )

    repo = StringIO(repo)

    # Ensure this is the file on the server
    return files.put(state, host, repo, filename)


@operation
def rpm(state, host, source, present=True):
    '''
    Install/manage ``.rpm`` file packages.

    + source: filenameo or URL of the ``.rpm`` package
    + present: whether ore not the package should exist on the system

    URL sources with ``present=False``:
        if the ``.rpm`` file isn't downloaded, pyinfra can't remove any existing package
        as the file won't exist until mid-deploy
    '''

    commands = []

    # If source is a url
    if urlparse(source).scheme:
        # Generate a temp filename (with .rpm extension to please yum)
        temp_filename = '{0}.rpm'.format(state.get_temp_filename(source))

        # Ensure it's downloaded
        commands.extend(files.download(state, host, source, temp_filename))

        # Override the source with the downloaded file
        source = temp_filename

    # Check for file .rpm information
    info = host.rpm_package(source)
    exists = False

    # We have info!
    if info:
        current_packages = host.rpm_packages

        if (
            info['name'] in current_packages
            and current_packages[info['name']] == info['version']
        ):
            exists = True

    # Package does not exist and we want?
    if present and not exists:
        commands.extend([
            'yum localinstall {0} -y'.format(source)
        ])

    # Package exists but we don't want?
    if exists and not present:
        commands.extend([
            'yum remove {0} -y'.format(info['name'])
        ])

    return commands


@operation
def packages(state, host, packages=None, present=True, upgrade=False, clean=False):
    '''
    Manage yum packages & updates.

    + packages: list of packages to ensure
    + present: whether the packages should be installed
    + upgrade: run yum upgrade
    + clean: run yum clean
    '''

    if packages is None:
        packages = []

    if isinstance(packages, basestring):
        packages = [packages]

    commands = []

    if clean:
        commands.append('yum clean all')

    if upgrade:
        commands.append('yum update -y')

    current_packages = host.rpm_packages or {}

    if current_packages is None:
        raise OperationException('yum is not installed')

    if present is True:
        # Packages specified but not installed
        diff_packages = [
            package for package in packages
            if package not in current_packages
        ]

        if diff_packages:
            commands.append('yum install -y {0}'.format(' '.join(diff_packages)))

    else:
        # Packages specified & installed
        diff_packages = [
            package for package in packages
            if package in current_packages
        ]

        if diff_packages:
            commands.append('yum remove -y {0}'.format(' '.join(diff_packages)))

    return commands
