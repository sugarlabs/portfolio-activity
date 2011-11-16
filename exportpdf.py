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
import time
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

    cr.set_font_size(40)
    cr.move_to(10, 50)
    cr.show_text(nick)
    cr.move_to(10, 100)
    cr.set_font_size(12)
    cr.show_text(time.strftime('%x', time.localtime()))
    cr.show_page()

    for i, dsobj in enumerate(activity.dsobjects):
        cr.set_font_size(40)
        cr.move_to(10, 50)
        if 'title' in dsobj.metadata:
            cr.show_text(dsobj.metadata['title'])
        else:
            cr.show_text(_('untitled'))

        try:
            w = 600
            h = 450
            pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(dsobj.file_path,
                                                          w, h)
        except(GError, IOError):
            try:
                w = 300
                h = 225
                pixbuf = get_pixbuf_from_journal(dsobj, w, h)
            except(GError, IOError):
                w = 0
                h = 0
                pixbuf = None

        cr.move_to(10, 150)
        if pixbuf is not None:
            cr.save()
            cr = gtk.gdk.CairoContext(cr)
            cr.set_source_pixbuf(pixbuf, 10, 150)
            cr.rectangle(10, 150, w, h)
            cr.fill()
            cr.restore()

        cr.set_font_size(12)
        cr.move_to(10, h + 175)
        if 'description' in dsobj.metadata:
            cr.show_text(dsobj.metadata['description'])
        cr.show_page()

    return tmp_file
