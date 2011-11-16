# -*- coding: utf-8 -*-
#Copyright (c) 2011 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA


import pygtk
pygtk.require('2.0')
import gtk
from glib import GError
import os.path
import cairo
from gettext import gettext as _

from utils import get_pixbuf_from_journal


def save_pdf(activity,  nick):
    ''' Output a PDF document from the title, pictures, and descriptions '''

    if len(activity.dsobjects) == 0:
        return None

    tmp_file = os.path.join(activity.datapath, 'output.pdf') 
    pdf_surface = cairo.PDFSurface(tmp_file, 600, 800)

    cr = cairo.Context(pdf_surface)
    cr.set_source_rgb(0, 0, 0)
    for i, dsobj in enumerate(activity.dsobjects):
        cr.set_font_size(40)
        cr.move_to(10, 50)
        if 'title' in dsobj.metadata:
            cr.show_text(dsobj.metadata['title'])
        else:
            cr.show_text(_('untitled'))

        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                dsobj.file_path, 800, 600)
        except(GError, IOError):
            try:
                pixbuf = get_pixbuf_from_journal(dsobj, 300, 225)
            except(GError, IOError):
                pixbuf = None

        cr.move_to(10, 150)
        if pixbuf is not None:
            cr.save()
            cr = gtk.gdk.CairoContext(cr)
            cr.set_source_pixbuf(pixbuf, 10, 150)
            cr.rectangle(10, 150, 300, 225)
            cr.fill()
            cr.restore()

        cr.set_font_size(12)
        cr.move_to(10, 400)
        if 'description' in dsobj.metadata:
            cr.show_text(dsobj.metadata['description'])
        cr.show_page()

    return tmp_file
