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

import gtk
import gobject
import os
import gobject

import pango

import sugar
from sugar.activity import activity
from sugar import profile
try:
    from sugar.graphics.toolbarbox import ToolbarBox
    _have_toolbox = True
except ImportError:
    _have_toolbox = False

if _have_toolbox:
    from sugar.bundle.activitybundle import ActivityBundle
    from sugar.activity.widgets import ActivityToolbarButton
    from sugar.activity.widgets import StopButton
    from sugar.graphics.toolbarbox import ToolbarButton

from sugar.graphics.toolbutton import ToolButton
from sugar.graphics.menuitem import MenuItem
from sugar.datastore import datastore
from sugar import mime
from sugar import profile

from sprites import Sprites, Sprite

from gettext import gettext as _

try:
    from sugar.graphics import style
    GRID_CELL_SIZE = style.GRID_CELL_SIZE
except ImportError:
    GRID_CELL_SIZE = 0

SERVICE = 'org.sugarlabs.PortfolioActivity'
IFACE = SERVICE
PATH = '/org/augarlabs/PortfolioActivity'


def _svg_str_to_pixbuf(svg_string):
    ''' Load pixbuf from SVG string '''
    pl = gtk.gdk.PixbufLoader('svg')
    pl.write(svg_string)
    pl.close()
    pixbuf = pl.get_pixbuf()
    return pixbuf


def _load_svg_from_file(file_path, width, height):
    '''Create a pixbuf from SVG in a file. '''
    return gtk.gdk.pixbuf_new_from_file_at_size(file_path, width, height)


def _button_factory(icon_name, tooltip, callback, toolbar, cb_arg=None,
                    accelerator=None):
    '''Factory for making toolbar buttons'''
    my_button = ToolButton(icon_name)
    my_button.set_tooltip(tooltip)
    my_button.props.sensitive = True
    if accelerator is not None:
        my_button.props.accelerator = accelerator
    if cb_arg is not None:
        my_button.connect('clicked', callback, cb_arg)
    else:
        my_button.connect('clicked', callback)
    if hasattr(toolbar, 'insert'):  # the main toolbar
        toolbar.insert(my_button, -1)
    else:  # or a secondary toolbar
        toolbar.props.page.insert(my_button, -1)
    my_button.show()
    return my_button


def _label_factory(label, toolbar):
    ''' Factory for adding a label to a toolbar '''
    my_label = gtk.Label(label)
    my_label.set_line_wrap(True)
    my_label.show()
    toolitem = gtk.ToolItem()
    toolitem.add(my_label)
    toolbar.insert(toolitem, -1)
    toolitem.show()
    return my_label


def _separator_factory(toolbar, visible=True, expand=False):
    ''' Factory for adding a separator to a toolbar '''
    separator = gtk.SeparatorToolItem()
    separator.props.draw = visible
    separator.set_expand(expand)
    toolbar.insert(separator, -1)
    separator.show()


LOWER = 1
DEFAULT = 2
UPPER = 30


def _slider_factory(tooltip, callback, toolbar, cb_arg=None):
    ''' Factory for adding a slider to a toolbar '''
    _adjustment = gtk.Adjustment(DEFAULT, LOWER, UPPER,
                                 1, 5, 0)
    _adjustment.connect('value_changed', callback)
    _range = gtk.HScale(_adjustment)
    _range.set_size_request(240, 15)
    _range_tool = gtk.ToolItem()
    _range_tool.add(_range)

    toolbar.insert(_range_tool, -1)
    return _adjustment


class PortfolioActivity(activity.Activity):
    ''' Make a slideshow from starred Journal entries. '''

    def __init__(self, handle):
        ''' Initialize the toolbars and the work surface '''
        super(PortfolioActivity, self).__init__(handle)

        self._setup_toolbars(_have_toolbox)
        self._setup_canvas()
        self._setup_workspace()

    def _setup_canvas(self):
        ''' Create a canvas '''

        self._canvas = gtk.DrawingArea()
        self._canvas.set_size_request(gtk.gdk.screen_width(),
                                      gtk.gdk.screen_height())
        self.set_canvas(self._canvas)
        self._canvas.show()
        self.show_all()

        self._canvas.set_flags(gtk.CAN_FOCUS)
        self._canvas.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self._canvas.add_events(gtk.gdk.BUTTON_RELEASE_MASK)
        self._canvas.add_events(gtk.gdk.POINTER_MOTION_MASK)
        self._canvas.connect("expose-event", self._expose_cb)

    def _setup_workspace(self):
        ''' Prepare to render the datastore entries. '''
        self._colors = profile.get_color().to_string().split(',')
        print self._colors

        self._width = gtk.gdk.screen_width()
        self._height = gtk.gdk.screen_height()
        self._scale = gtk.gdk.screen_width() / 1200.

        # Generate the sprites we'll need...
        self._sprites = Sprites(self._canvas)

        self._preview = None
        self._title = Sprite(self._sprites, 0, 0, _svg_str_to_pixbuf(
                _genblank(self._width, 40, self._colors)))
        self._description = Sprite(self._sprites, 50, 325, _svg_str_to_pixbuf(
                _genblank(self._width - 100, self._height - 400, self._colors)))
        self._my_canvas = Sprite(self._sprites, 0, 0,
                                gtk.gdk.Pixmap(self._canvas.window,
                                               self._width,
                                               self._height, -1))
        self._my_canvas.set_layer(0)
        self._my_gc = self._my_canvas.images[0].new_gc()

        self._my_canvas.set_layer(1)
        self._text_color = self._my_gc.get_colormap().alloc_color('#000000')
        self._fd = pango.FontDescription('Sans')

        self._clear_screen()

        self._find_starred()
        self.i = 0
        self._show_slide(self.i)

        self._playing = False
        self._rate = DEFAULT

    def _setup_toolbars(self, have_toolbox):
        ''' Setup the toolbars. '''

        self.max_participants = 1  # no sharing

        if have_toolbox:
            toolbox = ToolbarBox()

            # Activity toolbar
            activity_button = ActivityToolbarButton(self)

            toolbox.toolbar.insert(activity_button, 0)
            activity_button.show()

            self.set_toolbar_box(toolbox)
            toolbox.show()
            self.toolbar = toolbox.toolbar

        else:
            # Use pre-0.86 toolbar design
            primary_toolbar = gtk.Toolbar()
            toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(toolbox)
            toolbox.add_toolbar(_('Page'), primary_toolbar)
            toolbox.show()
            toolbox.set_current_toolbar(1)
            self.toolbar = primary_toolbar

        self._prev_button = _button_factory(
            'go-previous-inactive', _('Prev slide'), self._prev_cb,
            self.toolbar)

        self._next_button = _button_factory(
            'go-next', _('Next slide'), self._next_cb,
            self.toolbar)

        _separator_factory(self.toolbar)

        self._auto_button = _button_factory(
            'media-playlist-repeat', _('Autoplay'), self._autoplay_cb,
            self.toolbar)

        self._slider = _slider_factory(
            _('Adjust playback speed'), self._speed_cb, self.toolbar)

        if _have_toolbox:
            _separator_factory(toolbox.toolbar, False, True)

            stop_button = StopButton(self)
            stop_button.props.accelerator = '<Ctrl>q'
            toolbox.toolbar.insert(stop_button, -1)
            stop_button.show()

    def _expose_cb(self, win, event):
        ''' Have to refresh after a change in window status. '''
        self._sprites.redraw_sprites()
        return True

    def _destroy_cb(self, win, event):
        gtk.main_quit()

    def _find_starred(self):
        self._dsobjects, self._nobjects = datastore.find({'keep':'1'})
        return

    def _prev_cb(self, button=None):
        if self.i > 0:
            self.i -= 1
            self._show_slide(self.i)

    def _next_cb(self, button=None):
        if self.i < self._nobjects - 1:
            self.i += 1
            self._show_slide(self.i)

    def _autoplay_cb(self, button=None):
        if self._playing:
            print 'stop somehow'
            self._playing = False
            self._auto_button.set_icon('media-playlist-repeat')
            if hasattr(self, '_timeout_id') and self._timeout_id is not None:
                gobject.source_remove(self._timeout_id)
        else:
            self._playing = True
            self._auto_button.set_icon('media-playback-pause')
            self._loop()

    def _loop(self):
        self.i += 1
        if self.i == self._nobjects:
            self.i = 0
        self._show_slide(self.i)
        self._timeout_id = gobject.timeout_add(int(self._rate * 1000),
                                               self._loop)

    def _speed_cb(self, button=None):
        print self._slider.value
        self._rate = self._slider.value
        self._slider.set_value(int(self._rate + 0.5))

    def _clear_screen(self):
        self._my_gc.set_foreground(
            self._my_gc.get_colormap().alloc_color(self._colors[0]))
        rect = gtk.gdk.Rectangle(0, 0, self._width, self._height)
        self._my_canvas.images[0].draw_rectangle(self._my_gc, True, *rect)
        self.invalt(0, 0, self._width, self._height)

    def _show_slide(self, i):
        self._clear_screen()
        print self._dsobjects[i].metadata['title']

        if self.i == 0:
            self._prev_button.set_icon('go-previous-inactive')
        else:
            self._prev_button.set_icon('go-previous')
        if self.i == self._nobjects - 1:
            self._next_button.set_icon('go-next-inactive')
        else:
            self._next_button.set_icon('go-next')

        pixbuf = get_pixbuf_from_journal(self._dsobjects[i], 300, 225)
        if pixbuf is not None:
            if self._preview is None:
                self._preview = Sprite(self._sprites,
                                       int((self._width - 300) / 2), 60, pixbuf)
            else:
                self._preview.images[0] = pixbuf
            self._preview.set_layer(1000)
        else:
            if self._preview is not None:
                self._preview.hide()
            print 'pixbuf is None'
        self._title.set_label_attributes(24, rescale=False)

        self._title.set_label(self._dsobjects[i].metadata['title'])
        self._title.set_layer(1000)
        if 'description' in self._dsobjects[i].metadata:
            self._description.set_label(
                self._dsobjects[i].metadata['description'])
            self._description.set_layer(1000)
        else:
            self._description.set_label('')
            self._description.hide()
            print 'description is None'

    def invalt(self, x, y, w, h):
        ''' Mark a region for refresh '''
        self._canvas.window.invalidate_rect(
            gtk.gdk.Rectangle(int(x), int(y), int(w), int(h)), False)


def get_pixbuf_from_journal(dsobject, w, h):
    """ Load a pixbuf from a Journal object. """
    # _pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(dsobject.file_path,
    try:
        _pixbufloader = \
            gtk.gdk.pixbuf_loader_new_with_mime_type('image/png')
        _pixbufloader.set_size(min(300, int(w)), min(225, int(h)))
        _pixbufloader.write(dsobject.metadata['preview'])
        _pixbufloader.close()
        _pixbuf = _pixbufloader.get_pixbuf()
    except:
        _pixbuf = None
    return _pixbuf


def _genblank(w, h, colors):
    svg = SVG()
    svg.set_colors(colors)
    svg_string = svg.header(w, h)
    svg_string += svg.footer()
    return svg_string


class SVG:
    ''' SVG generators '''

    def __init__(self):
        self._scale = 1
        self._stroke_width = 1
        self._fill = '#FFFFFF'
        self._stroke = '#FFFFFF'

    def _svg_style(self, extras=""):
        return "%s%s%s%s%s%f%s%s%s" % ("style=\"fill:", self._fill, ";stroke:",
                                       self._stroke, ";stroke-width:",
                                       self._stroke_width, ";", extras,
                                       "\" />\n")

    def _svg_rect(self, w, h, rx, ry, x, y):
        svg_string = "       <rect\n"
        svg_string += "          width=\"%f\"\n" % (w)
        svg_string += "          height=\"%f\"\n" % (h)
        svg_string += "          rx=\"%f\"\n" % (rx)
        svg_string += "          ry=\"%f\"\n" % (ry)
        svg_string += "          x=\"%f\"\n" % (x)
        svg_string += "          y=\"%f\"\n" % (y)
        self.set_stroke_width(1.0)
        svg_string += self._svg_style()
        return svg_string

    def _background(self, w=80, h=60, scale=1):
        return self._svg_rect((w - 0.5) * scale, (h - 0.5) * scale,
                              1, 1, 0.25, 0.25)

    def header(self, w=80, h=60, scale=1, background=True):
        svg_string = "<?xml version=\"1.0\" encoding=\"UTF-8\""
        svg_string += " standalone=\"no\"?>\n"
        svg_string += "<!-- Created with Emacs -->\n"
        svg_string += "<svg\n"
        svg_string += "   xmlns:svg=\"http://www.w3.org/2000/svg\"\n"
        svg_string += "   xmlns=\"http://www.w3.org/2000/svg\"\n"
        svg_string += "   version=\"1.0\"\n"
        svg_string += "%s%f%s" % ("   width=\"", scale * w * self._scale,
                                  "\"\n")
        svg_string += "%s%f%s" % ("   height=\"", scale * h * self._scale,
                                  "\">\n")
        svg_string += "%s%f%s%f%s" % ("<g\n       transform=\"matrix(",
                                      self._scale, ",0,0,", self._scale,
                                      ",0,0)\">\n")
        if background:
            svg_string += self._background(w, h, scale)
        return svg_string

    def footer(self):
        svg_string = "</g>\n"
        svg_string += "</svg>\n"
        return svg_string

    def set_scale(self, scale=1.0):
        self._scale = scale

    def set_colors(self, colors):
        self._stroke = colors[0]
        self._fill = colors[1]

    def set_stroke_width(self, stroke_width=1.0):
        self._stroke_width = stroke_width

