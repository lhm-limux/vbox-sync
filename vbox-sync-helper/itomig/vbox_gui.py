# vim:set et sw=4 encoding=utf-8:
#
# Module to handle the distribution of VBox VM images
#
# © 2009 Joachim Breitner <joachim.breitner@itomig.de>
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

from itomig.vbox import Logger, VBoxImageFinder

import os.path

import pygtk
pygtk.require("2.0")
import gtk
import gtk.glade
import gobject
import threading
import tempfile
import gzip
import subprocess
from glob import glob
import shutil
from time import localtime, strftime
import locale
import debian.changelog


class PackageBuildingError(Exception):
    """This exception is thrown when someting goes wrong in the automated
    package building process."""
    pass

def current_email_address():
    # We abuse debchange to provide a proper username and email address
    (handle,tmp) = tempfile.mkstemp('','vbox-admin-')
    try:
        os.unlink(tmp) # debchange wants to create the file
        ret = subprocess.call(['debchange', '--create', '--newversion',  '0.0',
                               '--package', 'dummy', '--changelog', tmp, 'blubb'])
        if ret != 0:
            raise Exception, 'debchange failed'
        chlog = debian.changelog.Changelog(file=file(tmp))
        for block in chlog:
            return block.author
    finally:
        os.remove(tmp)

def bump_version_number(version):
    # We again abuse debchange
    (handle,tmp) = tempfile.mkstemp('','vbox-admin-')
    try:
        os.unlink(tmp) # debchange wants to create the file
        ret = subprocess.call(['debchange', '--create', '--newversion',  version,
                               '--package', 'dummy', '--changelog', tmp, 'blubb'])
        if ret != 0:
            raise Exception, 'debchange failed'
        ret = subprocess.call(['debchange', '--increment', '--changelog', tmp, 'blubb'])
        if ret != 0:
            raise Exception, 'debchange failed'
        chlog = debian.changelog.Changelog(file=file(tmp))
        return(str(chlog.version))
    finally:
        os.remove(tmp)

def dialogued_action(text, action):
    dlg = gtk.MessageDialog(flags = gtk.DIALOG_MODAL)
    dlg.props.text = text
    
    class Thread(threading.Thread):
        def run(self):
            action()
            dlg.destroy()

    thread = Thread().start()
    dlg.run()

class VBoxSyncAdminGui(object):
    def __init__(self, config):
        self.config = config
        self.logger = Logger()

        self.target_directory = os.getcwd()

        gladefile = os.path.join(os.path.dirname(__file__),"vbox-sync-admin.glade")
        assert os.path.exists(gladefile)

        self.wTree = gtk.glade.XML(gladefile)

        self.imagestore = gtk.ListStore(gobject.TYPE_PYOBJECT, gobject.TYPE_STRING)
        tv = self.wTree.get_widget("imagetreeview")
        tv.set_model(self.imagestore)
        tv.insert_column_with_attributes(-1,"Image",gtk.CellRendererText(),text=1)

        window = self.wTree.get_widget("vboxsyncadminwindow")
        # TODO Check for unsaved data here?
        window.connect("destroy", self.on_exit)
        self.wTree.get_widget("cancelbutton").connect("clicked", self.on_exit)
        

        self.wTree.get_widget("forwardbutton").connect("clicked", self.on_forward)
        self.wTree.get_widget("backbutton").connect("clicked", self.on_backward)
        self.wTree.get_widget("executebutton").connect("clicked", self.on_execute)
        self.wTree.get_widget("okbutton").connect("clicked", self.on_upload)

        self.switch_to(0)

        window.show()

    def fill_list_of_images(self):
        self.imagestore.clear()
        for image in VBoxImageFinder(self.config).find_images():
            self.imagestore.append(( image , image.name() ))

    def current_state(self):
        return self.wTree.get_widget("notebook").get_current_page()

    def on_backward(self, button):
        if self.current_state() == 1:
            dialogued_action("Entferne Kopie des Systemimages.",
                             self.image.leave_admin_mode)
            self.switch_to(0)
        
        elif self.current_state() == 2:
            self.switch_to(1)

        elif self.current_state() == 3:
            self.switch_to(2)

    def on_forward(self, button):
        if self.current_state() == 0:
            # Advancing from the image selecting frame
            sel = self.wTree.get_widget("imagetreeview").get_selection()
            (model,iter) = sel.get_selected()
            if not iter:
                return
            self.image = model.get(iter,0)[0]

            dialogued_action( "Kopiere Orginal-Systemimage (Dies kann eine Weile dauern).",
                               self.image.prepare_admin_mode )

            self.wTree.get_widget("packageentry").set_text(self.image.package_name)
            self.wTree.get_widget("versionentry").set_text(bump_version_number(self.image.image_version))
            self.wTree.get_widget("distributionentry").set_text("UNRELEASED")

            self.switch_to(1)

        elif self.current_state() == 1:
            self.switch_to(2)

        elif self.current_state() == 2:
            self.switch_to(3)

    def on_exit(self, widget):
        dialogued_action("Räume temporäre Dateien auf.",
                         self.cleanup)
        gtk.main_quit()

    def cleanup(self):
        # In case of abortion
        if self.current_state() >= 1:
            self.image.leave_admin_mode()
                
    def switch_to(self, new_state):
        if new_state == 0:
            self.fill_list_of_images()
            self.image = None

        elif new_state == 1:
            assert self.image

        elif new_state == 2:
            assert self.image

        self.wTree.get_widget("notebook").set_current_page(new_state)

    def on_execute(self, widget):
        assert self.current_state() == 1

        dialogued_action("Starte VirtualBox",
                         lambda: self.image.invoke( use_exec=False ))

    def on_upload(self, widget):
        assert self.current_state() == 3

        tmpdir = tempfile.mkdtemp('','vbox-admin-')
        try:
            os.chdir(tmpdir)

            package_name = self.wTree.get_widget("packageentry").get_text()
            package_version = self.wTree.get_widget("versionentry").get_text()
            package_changes = self.wTree.get_widget("changesentry").get_text()
            package_distribution = self.wTree.get_widget("distributionentry").get_text()

            locale.setlocale(locale.LC_ALL, 'C')
            date = strftime("%a, %d %b %Y %H:%M:%S %z", localtime())
            locale.setlocale(locale.LC_ALL, '')
            
            os.mkdir(package_name)
            os.chdir(package_name)

            os.mkdir("debian")
            file("debian/control", "w").write(
"""Source: %(package_name)s
Section: misc
Priority: extra
Maintainer: %(maintainer)s
Build-Depends: debhelper (>= 7)
Standards-Version: 3.8.2

Package: %(package_name)s
Architecture: all
Depends: ${misc:Depends}, vbox-sync-helper
Description: ${misc:Image} for VirtualBox
 Retrieves the ${misc:Image} image for VirtualBox from the central rsync
 repository and offers you access through the `${misc:Image}' command.
""" % { 'package_name' : package_name,
        'maintainer' : current_email_address() } )

            file("debian/rules", "w").write(
"""#!/usr/bin/make -f
PACKAGE=$(shell dpkg-parsechangelog | sed -ne 's/Source: *\\(.*\\) *$$/\\1/p')
IMAGE=$(shell echo $(PACKAGE) | sed -ne 's/-vbox$$//p')

build: build-stamp
build-stamp:
	dh_testdir

	touch build-stamp

clean:
	dh_testdir
	dh_testroot
	rm -f build-stamp

	dh_clean

install: build
	dh_testdir
	dh_testroot
	dh_prep
	dh_installdirs

# Build architecture-independent files here.
binary-indep: build install
	dh_testdir
	dh_testroot
	dh_installchangelogs
	dh_installdocs
	dh_installexamples
	dh_installman
	dh_link
	dh_compress
	dh_fixperms
	dh_vbox_sync $(IMAGE)
	dh_installdeb
	dh_gencontrol
	dh_md5sums
	dh_builddeb

binary-arch: build install

binary: binary-indep binary-arch
.PHONY: build clean binary-indep binary-arch binary install
""")

            file("debian/compat", "w").write("7")

            file("debian/changelog","w").write(
"""%(package_name)s (%(package_version)s) %(package_distribution)s; urgency=low

  * %(package_changes)s

 -- %(maintainer)s  %(date)s

""" % { 'package_name' : package_name,
        'package_version' : package_version,
        'package_changes' : package_changes,
        'package_distribution' : package_distribution,
        'maintainer' : current_email_address(),
        'date': date
        } )
    
            file("debian/changelog","a").write(
                gzip.GzipFile("/usr/share/doc/%s/changelog.gz" % self.image.package_name, "r").read())

            retcode = subprocess.call(['dpkg-buildpackage','-uc','-us'])
            if retcode != 0:
                raise PackageBuildingError("dpkg-buildpackage call failed")

            os.chdir("..")

            # Now look for the produced files
            generated_files = glob("*.changes") + glob("*.deb") + glob("*.dsc") + glob("*.tar.gz")
            for gen_file in generated_files:
                shutil.copy(gen_file, self.target_directory)
            # TODO Copy images to upload directory
        
        finally:
            os.chdir(self.target_directory)
            shutil.rmtree(tmpdir)

        dlg = gtk.MessageDialog(flags = gtk.DIALOG_MODAL, buttons = gtk.BUTTONS_OK)
        dlg.props.text = \
         "Paket erfolgreich gebaut. Die Dateien finden Sie im Verzeichnis %s." % \
         self.target_directory
        dlg.run()
        self.cleanup()
        gtk.main_quit()

    def main(self):
        gtk.gdk.threads_init()
        gtk.main()

