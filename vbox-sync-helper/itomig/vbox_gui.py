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
        window.connect("destroy", gtk.main_quit)

        self.wTree.get_widget("forwardbutton").connect("clicked", self.on_forward)

        self.switch_to(0)

        window.show()

    def fill_list_of_images(self):
        self.imagestore.clear()
        for image in VBoxImageFinder(self.config).find_images():
            self.imagestore.append(( image , image.name() ))

    def current_state(self):
        return self.wTree.get_widget("notebook").get_current_page()

    def on_forward(self, button):
        if self.current_state() == 0:
            # Advancing from the image selecting frame
            sel = self.wTree.get_widget("imagetreeview").get_selection()
            (model,iter) = sel.get_selected()
            if not iter:
                return
            self.image = model.get(iter,0)

            self.switch_to(1)

    def switch_to(self, new_state):
        if new_state == 0:
            self.fill_list_of_images()
            self.image = None

        if new_state == 1:
            assert self.image

        self.wTree.get_widget("notebook").set_current_page(new_state)

    def main(self):
        gtk.main()

