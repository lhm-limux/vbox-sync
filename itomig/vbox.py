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
# http://ec.europa.eu/idabc/7330l5
# 
# Unless required by applicable law or agreed to in
# writing, software distributed under the Licence is
# distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied.
# See the Licence for the specific language governing
# permissions and limitations under the Licence.

from ConfigParser import ConfigParser
import logging
import optparse
import os
import os.path
import subprocess
import tempfile

class ImageNotFoundError(Exception):
    pass

class RsyncError(Exception):
    pass

class TargetNotWriteableError(Exception):
    pass

class VBoxImageSync(object):
    def __init__(self, config, image_name, image_version):
        self.config = config
        self.image_name = image_name
        self.image_version = image_version
        self.logger = Logger()

    def _check_presence(self):
        """Submits a list request to the rsync server and raises
        ImageNotFoundError if rsync returns with a failure of 23
        (which is caused by ENOENT, among others) or raises
        RsyncError if rsync returns with any other error."""
        retcode = subprocess.call(['rsync', '-q', self._construct_url()])
        if retcode == 0:
            self.logger.debug('Image found on the server.')
            return
        elif retcode == 23:
            raise ImageNotFoundError
        else:
            raise RsyncError, retcode

    def _check_target_writeable(self):
        if not os.path.exists(self._construct_target()):
            return
        if not os.access(self._construct_target(), os.W_OK):
            raise TargetNotWriteableError

    def _ensure_target_directory(self):
        dir = os.path.dirname(self._construct_target())
        if not os.path.exists(dir):
            os.makedirs(dir, 0755)

    def _construct_url(self):
        """Constructs a URL to the image file we want to retrieve based
        on the baseurl we got from the configuration object."""
        # urlparse.urljoin is insufficient here because it recognizes
        # rsync URLs as being non-relative and generally does not what
        # we want here.
        image_path = '/'.join([self.image_name, self.image_version,
                               self._vdi_filename()])
        url = '/'.join([self.config.baseurl, image_path])
        return url

    def _construct_target(self):
        return os.path.join(self.config.target, self.image_name,
                            self._vdi_filename())

    def _vdi_filename(self):
        return '%s.vdi' % self.image_name

    def sync(self):
        self._check_presence()
        self._ensure_target_directory()
        self._check_target_writeable()
        self.logger.info('Syncing image')
        retcode = subprocess.call(['rsync', '--progress',
                                   self._construct_url(),
                                   self._construct_target()])


class VBoxImage(object):
    def __init__(self, config, image_name, image_version):
        self.config = config
        self.image_name = image_name
        self.image_version = image_version
        self.logger = Logger()

    def _make_vdi_immutable(self):
        self.logger.debug('Making the image immutable')
        subprocess.call(['vboxmanage', 'modifyhd', self._construct_target(),
                         'settype', 'immutable'])

    def sync(self):
        """This method syncs the image from the rsync server.  It delegates
        this to a VBoxImageSync object."""
        sync = VBoxImageSync(self.config, self.image_name, self.image_version)
        sync.sync()

    def register(self):
        self.logger.info('Registering the image with VirtualBox')
        self._make_vdi_immutable()

    def _vbox_home(self):
        return os.path.expanduser('~/.VirtualBox-%s' % self.image_name)

    def _ensure_vbox_home(self):
        vbox_home = self._vbox_home()
        # Create VBox home directory.
        if not os.path.exists(vbox_home):
            self.logger.debug('Creating VBox home for %s in %s',
                              self.image_name, vbox_home)
            os.makedirs(vbox_home, 0700)
        # Create data disk storage directory.
        if not os.path.exists(os.path.join(vbox_home, 'VDI')):
            os.makedirs(os.path.join(vbox_home, 'VDI'))
        os.environ['VBOX_USER_HOME'] = vbox_home

    def _ensure_data_disk(self, size=32):
        """Creates a data disk for use as the second harddrive in the
        VM with the passed size in megabytes."""
        # A temporary image we create.
        data_disk_tmp = tempfile.NamedTemporaryFile()
        data_disk = data_disk_tmp.name
        # The real image which will be used with VBox.
        data_disk_vdi = os.path.join(self._vbox_home(), 'VDI',
                                     '%s-data.vdi' % self.image_name)
        if os.path.exists(data_disk_vdi):
            # Do nothing.
            return
        self.logger.debug('Creating data disk image for %s.', self.image_name)
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
        ret = subprocess.call(['parted', data_disk, 'mklabel', 'msdos'])
        if ret != 0:
            raise Exception, 'parted-mklabel failed'
        # Create a fat16 or fat32 partition, depending on the size.  parted
        # complains if the partition is too tiny for fat32 but the minimum
        # size is determined by a strange algorithm.  In tests it already
        # worked with 64M, but not with 32M.  It's probably not advisable
        # to use fat32 on such tiny images anyway.
        if size >= 128:
            type = 'fat32'
        else:
            type = 'fat16'
        ret = subprocess.call(['parted', data_disk, 'mkpartfs', 'primary',
                               type, '1', str(size)])
        if ret != 0:
            raise Exception, 'parted-mkpartfs failed'
        # Now convert it using vboxmanage.
        ret = subprocess.call(['vboxmanage', 'convertfromraw', '-format',
                               'VDI', data_disk, data_disk_vdi])
        if ret != 0:
            raise Exception, 'vboxmanage-convertfromraw failed'
        # data_disk_vdi is now a disk usable for D:

    def _register_disks(self):
        pass

    def invoke(self):
        self._ensure_vbox_home()
        self._ensure_data_disk()
        self._register_disks()

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
    def __init__(self, usage):
        optparse.OptionParser.__init__(self, usage)
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

