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

def dialogued_action(text, action):
    dlg = gtk.MessageDialog()
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
            # Nothing to clean up here
            self.switch_to(0)
        
        elif self.current_state() == 2:
            dialogued_action("Removing copied system images",
                             self.image.leave_admin_mode)
            self.switch_to(1)

    def on_forward(self, button):
        if self.current_state() == 0:
            # Advancing from the image selecting frame
            sel = self.wTree.get_widget("imagetreeview").get_selection()
            (model,iter) = sel.get_selected()
            if not iter:
                return
            self.image = model.get(iter,0)[0]

            self.switch_to(1)

        elif self.current_state() == 1:
            self.switch_to(2)

    def on_exit(self, widget):
        dialogued_action("Cleaning up temporary files",
                         self.cleanup)
        gtk.main_quit()

    def cleanup(self):
        # In case of abortion
        if self.current_state() == 2:
            self.image.leave_admin_mode()
                
    def switch_to(self, new_state):
        if new_state == 0:
            self.fill_list_of_images()
            self.image = None

        if new_state == 1:
            assert self.image
            self.wTree.get_widget("packageentry").set_text(self.image.package_name)
            self.wTree.get_widget("versionentry").set_text(self.image.image_version)

        if new_state == 2:
            assert self.image

            dialogued_action( "Copying original image (this may take a while)",
                               self.image.prepare_admin_mode )

        self.wTree.get_widget("notebook").set_current_page(new_state)

    def main(self):
        gtk.gdk.threads_init()
        gtk.main()

