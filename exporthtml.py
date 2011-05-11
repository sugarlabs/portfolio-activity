# -*- coding: utf-8 -*-
#Copyright (c) 2011 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import pygtk
pygtk.require('2.0')
import gtk
import os.path
import subprocess
from cgi import escape
from gettext import gettext as _

from utils import get_pixbuf_from_journal, image_to_base64

# A dictionary to define the HTML wrappers around template elements
HTML_GLUE = {
    'doctype': '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 ' + \
        'Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">\n',
    'html': ('<html>\n', '</html>\n'),
    'html_svg': ('<html xmlns="http://www.w3.org/1999/xhtml">\n',
                 '</html>\n'),
    'head': ('<head>\n<!-- Created by Portfolio -->\n', '</head>\n'),
    'meta': '<meta http-equiv="content-type" content="text/html; ' + \
        'charset=UTF-8"/>\n',
    'title': ('<title>', '</title>\n'),
    'style': ('<style type="text/css">\n<!--\n', '-->\n</style>\n'),
    'body': ('<body>\n', '\n</body>\n'),
    'div': ('<div>\n', '</div>\n'),
    'slide': ('\n<a name="slide', '"></a>\n'),
    'h1': ('<h1>', '</h1>\n'),
    'table': ('<table cellpadding="10\'>\n', '</table>\n'),
    'tr': ('<tr>\n', '</tr>\n'),
    'td': ('<td valign="top" width="400" height="300">\n',
           '\n</td>\n'),
    'img': ('<img width="300" height="225" alt=' + \
                '"Image" src="data:image/png;base64,\n',
            '"/>\n'),
    'img2': ('<img width="800" height="600" alt=' + \
                '"Image" src="data:image/png;base64,\n',
            '"/>\n'),
    'ul': ('<table>\n', '</table>\n'),
    'li': ('<tr><td>', '</td></tr>\n')}

COMMENT = '<!--\n\<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"' + \
    ' "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" [\n\
    <!ENTITY ns_svg "http://www.w3.org/2000/svg">\n\
    <!ENTITY ns_xlink "http://www.w3.org/1999/xlink">\n\
]>\n\
-->\n'


def save_html(dsobjects, nick, tmp_path):
    ''' Output a series of HTML pages from the title, pictures, and
    descriptions '''

    htmlcode = ''
    if len(dsobjects) == 0:
        return None

    for i, dsobj in enumerate(dsobjects):
        htmlcode += HTML_GLUE['slide'][0] + str(i)
        htmlcode += HTML_GLUE['slide'][1] + \
            HTML_GLUE['div'][0]
        if 'title' in dsobj.metadata:
            htmlcode += HTML_GLUE['h1'][0] + \
                dsobj.metadata['title'] + \
                HTML_GLUE['h1'][1]

        pixbuf = None
        media_object = False
        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                dsobj.file_path, 800, 600)
            key = 'img2'
        except:
            pixbuf = get_pixbuf_from_journal(dsobj, 300, 225)
            key = 'img'

        if pixbuf is not None:
            tmp = HTML_GLUE[key][0]
            tmp += image_to_base64(pixbuf, tmp_path)
            tmp += HTML_GLUE[key][1]

        if 'description' in dsobj.metadata:
            tmp += '<p>' + dsobj.metadata['description'] + '</p>'

        htmlcode += tmp + \
            HTML_GLUE['div'][1]

    return HTML_GLUE['doctype'] + \
        HTML_GLUE['html'][0] + \
        HTML_GLUE['head'][0] + \
        HTML_GLUE['meta'] + \
        HTML_GLUE['title'][0] + \
        nick + ' ' + _('Portfolio') + \
        HTML_GLUE['title'][1] + \
        HTML_GLUE['style'][0] + \
        HTML_GLUE['style'][1] + \
        HTML_GLUE['head'][1] + \
        HTML_GLUE['body'][0] + \
        htmlcode + \
        HTML_GLUE['body'][1] + \
        HTML_GLUE['html'][1]
