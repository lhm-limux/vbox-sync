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

from itomig.vbox import Logger

import os.path

import pygtk
pygtk.require("2.0")
import gtk
import gtk.glade

class VBoxSyncAdminGui(object):
    def __init__(self, config):
        self.config = config
        self.logger = Logger()

        gladefile = os.path.join(os.path.dirname(__file__),"vbox-sync-admin.glade")
        assert os.path.exists(gladefile)

        self.wTree = gtk.glade.XML(gladefile)
        self.window = self.wTree.get_widget("vboxsyncadminwindow")

        self.window.show()


    def main(self):
        gtk.main()

