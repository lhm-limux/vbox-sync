# vim:set et sw=4 encoding=utf-8:
#
# Module to handle the distribution of VBox VM images
#
# © 2009 Philipp Kern <philipp.kern@itomig.de>
#
# Licensed under the EUPL, Version 1.0 or – as soon they
# will be approved by the European Commission - subsequent
# versions of the EUPL (the "Licence");
# you may not use this work except in compliance with the
# Licence.
# You may obtain a copy of the Licence at:
# 
# http://ec.europa.eu/idabc/eupl
# 
# Unless required by applicable law or agreed to in
# writing, software distributed under the Licence is
# distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied.
# See the Licence for the specific language governing
# permissions and limitations under the Licence.

"""
This module fetches VirtualBox images from a rsync server specified
in a configuration file and handles its user-local registration and
invocation.
"""

__VERSION__ = "@VERSION@"

from ConfigParser import ConfigParser
import logging
import optparse
import os
import os.path
import subprocess
import sys
import tempfile

class ImageNotFoundError(Exception):
    """This exception is raised when the specified image cannot be found
    with the given version on the rsync server (vbox-sync) or if the image
    was expected on the local disk and not found (vbox-invoke).
    """
    pass

class RsyncError(Exception):
    """This exception is raised when the rsync invocation to fetch the
    image or to list the directory on the server fails with a different
    error than 'File Not Found'.  For the latter, see ImageNotFoundError.
    """
    pass

class TargetNotWriteableError(Exception):
    """This exception is raised when the target direction of the sync
    operation is not writeable, which is commonly the case if the target
    directory is only writeable as root and the script is invoked as a
    normal, unprivileged user."""
    pass

class VBoxImageSync(object):
    def __init__(self, image):
        self.image = image
        self.config = image.config
        self.image_name = image.image_name
        self.image_version = image.image_version
        self.logger = image.logger

    def _check_presence(self):
        self._check_rsync_file(self._construct_url(self.image.vdi_filename()))
        self._check_rsync_file(self._construct_url(self.image.cfg_filename()))

    def _check_rsync_file(self, filename):
        """Submits a list request to the rsync server and raises
        ImageNotFoundError if rsync returns with a failure of 23
        (which is caused by ENOENT, among others) or raises
        RsyncError if rsync returns with any other error."""
        retcode = subprocess.call(['rsync', '-q', filename])
        if retcode == 0:
            self.logger.debug('Image found on the server.')
            return
        elif retcode == 23:
            raise ImageNotFoundError
        else:
            raise RsyncError, retcode

    def _check_target_writeable(self):
        if not os.path.exists(self.image.vdi_path()):
            return
        if not os.access(self.image.vdi_path(), os.W_OK):
            raise TargetNotWriteableError

    def _ensure_target_directory(self):
        basedir = os.path.dirname(self.image.vdi_path())
        if not os.path.exists(basedir):
            os.makedirs(basedir, 0755)

    def _construct_url(self, filename):
        """Constructs a URL to the image file we want to retrieve based
        on the baseurl we got from the configuration object."""
        # urlparse.urljoin is insufficient here because it recognizes
        # rsync URLs as being non-relative and generally does not what
        # we want here.
        image_path = '/'.join([self.image_name, self.image_version, filename])
        url = '/'.join([self.config.baseurl, image_path])
        return url

    def _sync_file(self, source, target):
        retcode = subprocess.call(['rsync', '--progress', '--times',
                                   source, target])
        if retcode != 0:
            raise RsyncError, retcode
        # Make it publically readable, do not inherit the permission
        # even if copied from the local disk.
        os.chmod(target, 0644)

    def sync(self):
        self._check_presence()
        self._ensure_target_directory()
        self._check_target_writeable()
        self.logger.info('Syncing image')
        self._sync_file(self._construct_url(self.image.cfg_filename()),
                        self.image.cfg_path())
        self._sync_file(self._construct_url(self.image.vdi_filename()),
                        self.image.vdi_path())

class VBoxInvocationError(Exception):
    pass

def guarded_vboxmanage_call(args):
    cmdline = ['VBoxManage', '-nologo'] + args
    retcode = subprocess.call(cmdline)
    if retcode != 0:
        raise VBoxInvocationError, ' '.join(cmdline)

class VBoxImage(object):
    def __init__(self, config, image_name, image_version):
        self.config = config
        self.image_name = image_name
        self.image_version = image_version
        self.logger = Logger()
        self.disks = dict()

    def cfg_filename(self):
        return '%s.cfg' % self.image_name

    def vdi_filename(self):
        return '%s.vdi' % self.image_name

    def _target_path(self, filename):
        return os.path.join(self.config.target, self.image_name, filename)

    def vdi_path(self):
        return self._target_path(self.vdi_filename())

    def cfg_path(self):
        return self._target_path(self.cfg_filename())

    def sync(self):
        """This method syncs the image from the rsync server.  It delegates
        this to a VBoxImageSync object."""
        sync = VBoxImageSync(self)
        sync.sync()

    def register(self):
        self.logger.info('Registering the image with VirtualBox')
        self._make_vdi_immutable()

    def _vbox_home(self):
        path = '~/.VirtualBox-%s' % self.image_name
        return os.path.abspath(os.path.expanduser(path))

    def _ensure_vbox_home(self):
        vbox_home = self._vbox_home()
        # Create VBox home directory.
        if not os.path.exists(vbox_home):
            self.logger.info('Creating VBox home for %s in %s',
                             self.image_name, vbox_home)
            os.makedirs(vbox_home, 0700)
        # Create data disk storage directory.
        if not os.path.exists(os.path.join(vbox_home, 'VDI')):
            os.makedirs(os.path.join(vbox_home, 'VDI'))
        os.environ['VBOX_USER_HOME'] = vbox_home

    def _ensure_data_disk(self, size=32):
        """Creates a data disk for use as the second harddrive in the
        VM with the passed size in megabytes.  The data disk will not be
        resized in any way if the given size differs from the on-disk
        image."""
        # A temporary image we create.
        data_disk_tmp = tempfile.NamedTemporaryFile()
        data_disk = data_disk_tmp.name
        # The real image which will be used with VBox.
        data_disk_vdi = os.path.join(self._vbox_home(), 'VDI',
                                     '%s-data.vdi' % self.image_name)
        if os.path.exists(data_disk_vdi):
            # Do nothing.
            return
        self.logger.info('Creating data disk image for %s.', self.image_name)
        # First create an empty image full of zeros.  This needs some
        # space in the temporary directory, but avoids that a template needs
        # to be shipped separately.  VirtualBox is compressing the image
        # when converting from RAW to VDI anyway (32M to 1M in tests with
        # fat16).
        ret = subprocess.call(['dd', 'if=/dev/zero', 'of=%s' % data_disk,
                               'bs=1M', 'count=%d' % size])
        # XXX: improve exceptions here
        # XXX: catch stderr+stdout and only print it if something goes wrong
        if ret != 0:
            raise Exception, 'dd failed'
        # Now create a DOS disk label.
        # (The path to parted is explicitly specified, because /sbin is not
        # always in the path.  Maybe this should be replaced by an
        # environment modification later on.)
        ret = subprocess.call(['/sbin/parted', data_disk, 'mklabel', 'msdos'])
        if ret != 0:
            raise Exception, 'parted-mklabel failed'
        # Create a fat16 or fat32 partition, depending on the size.  parted
        # complains if the partition is too tiny for fat32 but the minimum
        # size is determined by a strange algorithm.  In tests it already
        # worked with 64M, but not with 32M.  It's probably not advisable
        # to use fat32 on such tiny images anyway.
        if size >= 128:
            fs_type = 'fat32'
        else:
            fs_type = 'fat16'
        ret = subprocess.call(['/sbin/parted', data_disk, 'mkpartfs', 'primary',
                               fs_type, '1', str(size)])
        if ret != 0:
            raise Exception, 'parted-mkpartfs failed'
        # Now convert it using VBoxManage.
        guarded_vboxmanage_call(['convertfromraw', '-format', 'VDI',
                                 data_disk, data_disk_vdi])
        # This destroys the temporary image.
        data_disk_tmp.close()
        # data_disk_vdi is now a disk usable for D:
        self.disks['data'] = data_disk_vdi

    def _register_disks(self):
        for disk in self.disks:
            if disk == 'system':
                disk_type = 'immutable'
            elif disk == 'data':
                # TODO: Do we want that?  Causes it to be unaffected by
                # snapshots.
                disk_type = 'writethrough'
            else:
                disk_type = 'normal'
            self.vbox_registry.register_hdd(self.disks[disk], disk_type)

    def _register_vm(self):
        # XXX: Maybe update settings only after upgrades?  That's the only
        # part that would require passing in the version on the command-line.
        # TODO: We really need to change this, as the immutability of the
        # system disk creates differential images that are assigned to the
        # ide port instead
        uuid = self.vbox_registry.create_vm(self.image_name)
        # Read the supplied configuration file for VM parameters.
        parser = ConfigParser()
        parser.read(self.cfg_path())
        # ConfigParser's items method gives us a list of tuples.  The map
        # will unquote the values (i.e. remove spaces and quotes) and prepend
        # a dash to the keys to act as the parameters.  In the end it's casted
        # to a dict for later modification.
        parameters = dict(map(lambda t: ('-%s' % t[0], t[1].strip(' "\'')),
                              parser.items('vmparameters')))
        self.vbox_registry.modify_vm(uuid, parameters)
        for disk in self.disks:
            # TODO: improve this
            if disk == 'system':
                ide_port = 'hda'
            elif disk == 'data':
                ide_port = 'hdb'
            else:
                raise NotImplementedError, 'disks other than system and data '\
                                           'implemented'
            self.vbox_registry.attach_hdd(uuid, ide_port, self.disks[disk])

    def _ensure_system_disk(self):
        if not os.path.exists(self.vdi_path()):
            raise ImageNotFoundError
        self.disks['system'] = self.vdi_path()

    def invoke(self):
        self._ensure_vbox_home()
        self.vbox_registry = VBoxRegistry(self._vbox_home())
        self._ensure_system_disk()
        self._ensure_data_disk()
        self._register_disks()
        self._register_vm()
        # Using execlp to replace the current process image.
        # XXX: do we want that?  function does not return
        os.execlp('VBoxManage', 'VBoxManage', '-nologo',
                  'startvm', self.image_name)
        # TODO: make this configurable to either use SDL or VBox proper
        #os.execlp('vboxsdl', '-vm', self.image_name)

class VBoxRegistry(object):
    # XXX: handle failures
    def __init__(self, vbox_home):
        self.vbox_home = vbox_home
        self.logger = Logger()
        # TODO: pass this through subprocess
        if vbox_home:
            os.environ['VBOX_USER_HOME'] = vbox_home

    def _get_list_value(self, line):
        return line.split(' ', 1)[1].strip()

    def get_vms(self):
        p = subprocess.Popen(['VBoxManage', '-nologo', 'list', 'vms'],
                             stdout=subprocess.PIPE)
        vms, current_name = {}, None
        output = p.communicate()[0]
        for line in output.splitlines():
            # XXX: test if this is locale dependent
            if line.startswith('Name:'):
                current_name = self._get_list_value(line)
            elif line.startswith('UUID:'):
                uuid = self._get_list_value(line)
                vms[uuid] = current_name
        return vms

    def get_hdds(self):
        p = subprocess.Popen(['VBoxManage', '-nologo', 'list', 'hdds'],
                             stdout=subprocess.PIPE)
        output = p.communicate()[0]
        hdds = []
        for line in output.splitlines():
            if line.startswith('Location:'):
                hdds.append(self._get_list_value(line))
        return hdds

    def create_vm(self, name):
        """Registers a new VM with VirtualBox and returns its UUID."""
        vms = self.get_vms()
        for uuid in vms:
            if vms[uuid] == name:
                return uuid
        # VM does not exist already, create it in the registry.
        p = subprocess.Popen(['VBoxManage', '-nologo', 'createvm',
                              '-name', name, '-register'],
                             stdout=subprocess.PIPE)
        output = p.communicate()[0]
        for line in output.splitlines():
            if line.startswith('UUID:'):
                return self._get_list_value(line)
        # TODO: No UUID found, something went wrong inside vbox.  We should
        # raise an exception instead.
        assert False

    def modify_vm(self, identifier, parameters):
        """Takes the VM identifier (either name or UUID) and a dict of
        parameters and adjusts the VM parameters accordingly through
        VBoxManage."""
        # XXX: We should interact with vbox more sanely.  Sadly vbox's CLI
        # interface is not machine-parseable, so that's hard.
        arg_list = []
        for key in parameters:
            arg_list.extend([key, str(parameters[key])])
        guarded_vboxmanage_call(['modifyvm', identifier] + arg_list)

    def register_hdd(self, filename, disk_type='normal'):
        """Registers a VDI file with the VirtualBox media registry.

        Supported disk types: normal, immutable and writethrough

        Returns True if a change has been done to the registry and False
        if the image was already registered.
        """
        # VirtualBox always works with absolute paths.  So we need to
        # work with those too, unless everything will be messed up.
        absolute_filename = os.path.abspath(filename)
        if absolute_filename in self.get_hdds():
            # Nothing to do, it's already registered.
            return False
        self.logger.debug('Registering new hard disk image %s with type %s.',
                          absolute_filename, disk_type)
        guarded_vboxmanage_call(['openmedium', 'disk',
                                 os.path.abspath(filename),
                                 '-type', disk_type])
        return True

    def attach_hdd(self, identifier, ide_port, disk_identifier):
        """Attaches a hard disk image to a VM ide port by detaching the old
        and attaching the new image.  This works around failures by VirtualBox
        if differential hard disks are already attached."""
        # TODO: (IMPORTANT!) get rid of the differential disk leftover
        # disconnect current HDD
        guarded_vboxmanage_call(['modifyvm', identifier, '-%s' % ide_port,
                                 'none'])
        # attach the new one
        guarded_vboxmanage_call(['modifyvm', identifier, '-%s' % ide_port,
                                 disk_identifier])

    # The machine-readable output of VBoxManage showvminfo needs severe fixups
    # to be used as input for modifyvm's command-line interface.  The following
    # dict specified which keys to discard (by setting them to False) and which
    # keys to fix up because they are named differently, by specifying a
    # replacement name.
    _transform_vminfo_keys = {
        'name': False,
        'UUID': False,
        'CfgFile': False,
        'VMState': False,
        'VMStateChangeTime': False,
        'GuestStatisticsUpdateInterval': False,
        'bootmenu': 'biosbootmenu',
        'hda': False,
        'hdb': False,
        'hdc': False,
        'hdd': False,
        }

    def dump_vm_config(self, identifier, output_file=None):
        # XXX: We can get rid of this ad-hoc configuration file if we switch to
        # the OVF format.
        if output_file:
            f = output_file
        else:
            f = sys.stdout
        p = subprocess.Popen(['VBoxManage', '-nologo', 'showvminfo',
                              identifier, '-machinereadable'],
                             stdout=subprocess.PIPE)
        output = p.communicate()[0]
        f.write("[vmparameters]\n")
        for line in output.splitlines():
            for pattern in self._transform_vminfo_keys:
                if line is None:
                    continue
                if line.startswith(pattern):
                    if self._transform_vminfo_keys[pattern] is False:
                        line = None
                    else:
                        line = '%s%s' % (self._transform_vminfo_keys[pattern],
                                         line[len(pattern):])
            if not line:
                continue
            f.write(line)
            f.write("\n")

class Config(object):
    """Configuration object that reads ~/.config/vbox-sync.cfg
    and /etc/vbox-sync.cfg iff they exist and overrides settings
    based on the command-line options passed by the user."""

    def __init__(self, options):
        self._read_config_files()

        if options:
            self._read_cmdline_options(options)

        logger = Logger()
        logger.debug('Configuration:')
        logger.debug(' Rsync Base URL: %s', self.baseurl)
        logger.debug(' Target directory: %s', self.target)

    def _read_config_files(self):
        # Read configuration file.
        file_config = ConfigParser()
        file_config.read([os.path.expanduser('~/.config/vbox-sync.cfg'),
                         '/etc/vbox-sync.cfg'])
        self.baseurl = file_config.get('rsync', 'baseurl')
        self.target = file_config.get('images', 'target')

    def _read_cmdline_options(self, options):
        if getattr(options, 'baseurl', None):
            self.baseurl = options.baseurl
        if getattr(options, 'target', None):
            self.target = options.target

class OptionParser(optparse.OptionParser):
    """An almost-normal OptionParser object, with the difference that it
    sets logging to DEBUG if -d is passed.  As this is wanted for all
    callees of this module we implement it centrally.
    """
    def __init__(self, usage):
        optparse.OptionParser.__init__(self, usage,
                                       version="%prog " + __VERSION__)
        self.add_option('-d', '--debug', dest='debug',
                        help='enables debugging output',
                        action='callback', callback=self._enable_debug)

    def _enable_debug(self, option, opt, value, parser):
        Logger().setLevel(logging.DEBUG)

_logger = None

def Logger():
    """Logger singleton based on a named logger provided by the logging
    module."""
    global _logger
    if _logger:
        return _logger
    _logger = logging.getLogger('itomig.vbox')
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(name)s: %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    return _logger

