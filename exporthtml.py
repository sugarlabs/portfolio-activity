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
from cgi import escape
from gettext import gettext as _

from utils import get_pixbuf_from_journal, image_to_base64, file_to_base64

# A dictionary to define the HTML wrappers around template elements
HTML_GLUE = {
    'doctype': '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 \
Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">\n',
    'html': ('<html>\n', '</html>\n'),
    'html_svg': ('<html xmlns="http://www.w3.org/1999/xhtml">\n',
                 '</html>\n'),
    'head': ('<head>\n<!-- Created by Portfolio -->\n', '</head>\n'),
    'meta': '<meta http-equiv="content-type" content="text/html; \
charset=UTF-8"/>\n',
    'title': ('<title>', '</title>\n'),
    'body': ('<body><center>\n', '\n</center></body>\n'),
    'div': ('<div class="box">\n', '</div>\n'),
    'slide': ('\n<a name="slide', '"></a>\n'),
    'h1': ('<p class="head">', '</p>\n'),
    'audio': ('<embed src="data:audio/ogg;base64,\n',
              '" controller="true" autoplay="false" autostart="false" \
type="audio/ogg" />\n'),
    'img': ('<img width="300" height="225" alt=\
"Image" src="data:image/png;base64,\n',
            '"/>\n'),
    'img2': ('<img width="600" height="450" alt=\
"Image" src="data:image/png;base64,\n',
            '"/>\n')}

COMMENT = '<!--\n\<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" \
"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" [\n\
    <!ENTITY ns_svg "http://www.w3.org/2000/svg">\n\
    <!ENTITY ns_xlink "http://www.w3.org/1999/xlink">\n\
]>\n\
-->\n'


def save_html(activity,  nick):
    ''' Output a series of HTML pages from the title, pictures, and
    descriptions '''

    htmlcode = ''
    if len(activity.dsobjects) == 0:
        return None

    for i, dsobj in enumerate(activity.dsobjects):
        htmlcode += HTML_GLUE['slide'][0] + str(i)
        htmlcode += HTML_GLUE['slide'][1] + \
            HTML_GLUE['div'][0]
        if 'title' in dsobj.metadata:
            htmlcode += HTML_GLUE['h1'][0] + \
                dsobj.metadata['title'] + \
                HTML_GLUE['h1'][1]
        else:
            htmlcode += HTML_GLUE['h1'][0] + \
                _('untitled') + \
                HTML_GLUE['h1'][1]

        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                dsobj.file_path, 800, 600)
            image_key = 'img2'
        except(GError, IOError):
            try:
                pixbuf = get_pixbuf_from_journal(dsobj, 300, 225)
                image_key = 'img'
            except(GError, IOError):
                pixbuf = None

        if pixbuf is not None:
            tmp = HTML_GLUE[image_key][0]
            tmp += image_to_base64(pixbuf, activity.datapath)
            tmp += HTML_GLUE[image_key][1]
        else:  # No image
            tmp = ''

        if 'description' in dsobj.metadata:
            tmp += HTML_GLUE['body'][0] \
                + dsobj.metadata['description'] + \
                HTML_GLUE['body'][1]

        audio_obj = activity._search_for_audio_note(dsobj.object_id)
        if audio_obj is not None:
            tmp += HTML_GLUE['audio'][0]
            tmp += file_to_base64(audio_obj.file_path, activity.datapath)
            tmp += HTML_GLUE['audio'][1]

        htmlcode += tmp + \
            HTML_GLUE['div'][1]

    return HTML_GLUE['doctype'] + \
        HTML_GLUE['html'][0] + \
        HTML_GLUE['head'][0] + \
        HTML_GLUE['meta'] + \
        HTML_GLUE['title'][0] + \
        nick + ' ' + _('Portfolio') + \
        HTML_GLUE['title'][1] + \
        '<style type="text/css">\n<!--\n-->\nbody {background-color:' + \
activity.colors[0] + ';}\np.head {font-size: 18pt; font-weight: bold; \
font-family: "Sans"; }\np.body  {font-size: 12pt; font-weight: regular; \
font-family: "Sans"; }\ndiv.box{width:630px; padding:10px; border:5px; \
margin:7px; background:' + activity.colors[1] + '}\n</style>\n' +\
        HTML_GLUE['head'][1] + \
        HTML_GLUE['body'][0] + \
        htmlcode + \
        HTML_GLUE['body'][1] + \
        HTML_GLUE['html'][1]
