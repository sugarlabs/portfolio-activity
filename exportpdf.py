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

import os.path
import time
import json

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from glib import GError
from gi.repository import Pango
from gi.repository import PangoCairo
import cairo

from gettext import gettext as _

from utils import get_pixbuf_from_journal, parse_comments

import logging
_logger = logging.getLogger("portfolio-activity")


PAGE_WIDTH = 504
PAGE_HEIGHT = 648
LEFT_MARGIN = 10
TOP_MARGIN = 20


def save_pdf(activity, nick, description=None):
    ''' Output a PDF document from the title, pictures, and descriptions '''

    if len(activity.dsobjects) == 0:
        return None

    head = activity.title_size
    body = activity.desc_size / 2

    tmp_file = os.path.join(activity.datapath, 'output.pdf')
    pdf_surface = cairo.PDFSurface(tmp_file, 504, 648)

    fd = Pango.FontDescription('Sans')
    cr = cairo.Context(pdf_surface)
    cr.set_source_rgb(0, 0, 0)

    show_text(cr, fd, nick, head, LEFT_MARGIN, TOP_MARGIN)
    show_text(cr, fd, time.strftime('%x', time.localtime()),
              body, LEFT_MARGIN, TOP_MARGIN + 3 * head)
    if description is not None:
        show_text(cr, fd, description,
                  body, LEFT_MARGIN, TOP_MARGIN + 4 * head)
    cr.show_page()

    for i, dsobj in enumerate(activity.dsobjects):
        if dsobj.metadata['keep'] == '0':
            continue
        if 'title' in dsobj.metadata:
            show_text(cr, fd, dsobj.metadata['title'], head, LEFT_MARGIN,
                      TOP_MARGIN)
        else:
            show_text(cr, fd, _('untitled'), head, LEFT_MARGIN,
                      TOP_MARGIN)

        w = 0
        h = 0
        pixbuf = None
        if os.path.exists(dsobj.file_path):
            print dsobj.file_path
            try:
                w = int(PAGE_WIDTH - LEFT_MARGIN * 2)
                h = int(w * 3 / 4)
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                    dsobj.file_path, w, h)
            except: # (GError, IOError):
                try:
                    w = 300
                    h = 225
                    pixbuf = get_pixbuf_from_journal(dsobj, w, h)
                except: # (GError, IOError):
                    pass

        if pixbuf is not None:
            cr.save()
            Gdk.cairo_set_source_pixbuf(
                cr, pixbuf, LEFT_MARGIN, TOP_MARGIN + 150)
            cr.rectangle(LEFT_MARGIN, TOP_MARGIN + 150, w, h)
            cr.fill()
            cr.restore()

        text = ''
        if 'description' in dsobj.metadata:
            text += dsobj.metadata['description']
        if 'comments' in dsobj.metadata:
            text += '\n'
            text += parse_comments(json.loads(dsobj.metadata['comments']))
        show_text(cr, fd, text, body, LEFT_MARGIN, h + 175)

        cr.show_page()

    return tmp_file


def show_text(cr, fd, label, size, x, y):
    pl = PangoCairo.create_layout(cr)
    fd.set_size(int(size * Pango.SCALE))
    pl.set_font_description(fd)
    if type(label) == str or type(label) == unicode:
        pl.set_text(label.replace('\0', ' '), -1)
    else:
        pl.set_text(str(label), -1)
    pl.set_width((PAGE_WIDTH - LEFT_MARGIN * 2) * Pango.SCALE)
    cr.save()
    cr.translate(x, y)
    PangoCairo.update_layout(cr, pl)
    PangoCairo.show_layout(cr, pl)
    cr.restore()
