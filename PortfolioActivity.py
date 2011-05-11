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

from sugar.graphics.menuitem import MenuItem
from sugar.datastore import datastore
from sugar import mime
from sugar import profile

from sprites import Sprites, Sprite
from exporthtml import save_html
from utils import get_path, lighter_color, svg_str_to_pixbuf, \
    load_svg_from_file, button_factory, label_factory, separator_factory, \
    slider_factory, get_pixbuf_from_journal, genblank, get_hardware

from gettext import gettext as _

try:
    from sugar.graphics import style
    GRID_CELL_SIZE = style.GRID_CELL_SIZE
except ImportError:
    GRID_CELL_SIZE = 0

SERVICE = 'org.sugarlabs.PortfolioActivity'
IFACE = SERVICE
PATH = '/org/augarlabs/PortfolioActivity'

# Size and position of title, preview image, and description
PREVIEWW = 450
PREVIEWH = 338
PREVIEWY = 80
FULLW = 800 
FULLH = 600
TITLEH = 60
DESCRIPTIONH = 350
DESCRIPTIONX = 50
DESCRIPTIONY = 450
SHORTH = 100
SHORTX = 50
SHORTY = 700


class PortfolioActivity(activity.Activity):
    ''' Make a slideshow from starred Journal entries. '''

    def __init__(self, handle):
        ''' Initialize the toolbars and the work surface '''
        super(PortfolioActivity, self).__init__(handle)

        self._tmp_path = get_path(activity, 'instance')

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

        # Use the lighter color for the text background
        if lighter_color(self._colors) == 0:
            tmp = self._colors[0]
            self._colors[0] = self._colors[1]
            self._colors[1] = tmp

        self._width = gtk.gdk.screen_width()
        self._height = gtk.gdk.screen_height()
        self._scale = gtk.gdk.screen_height() / 900.

        if get_hardware()[0:2] == 'XO':
            titlef = 18
            descriptionf = 12
        else:
            titlef = 36
            descriptionf = 24

        # Generate the sprites we'll need...
        self._sprites = Sprites(self._canvas)

        self._title = Sprite(self._sprites, 0, 0, svg_str_to_pixbuf(
                genblank(self._width, int(TITLEH * self._scale),
                          self._colors)))
        self._title.set_label_attributes(int(titlef * self._scale),
                                         rescale=False)
        self._preview = Sprite(self._sprites,
            int((self._width - int(PREVIEWW * self._scale)) / 2),
            int(PREVIEWY * self._scale), svg_str_to_pixbuf(genblank(
                    int(PREVIEWW * self._scale), int(PREVIEWH * self._scale),
                    self._colors)))

        self._full_screen = Sprite(self._sprites,
            int((self._width - int(FULLW * self._scale)) / 2),
            int(PREVIEWY * self._scale), svg_str_to_pixbuf(
                genblank(int(FULLW * self._scale), int(FULLH * self._scale),
                          self._colors)))

        self._description = Sprite(self._sprites,
                                   int(DESCRIPTIONX * self._scale),
                                   int(DESCRIPTIONY * self._scale),
                                   svg_str_to_pixbuf(
                genblank(int(self._width - (2 * DESCRIPTIONX * self._scale)),
                          int(DESCRIPTIONH * self._scale),
                          self._colors)))
        self._description.set_label_attributes(int(descriptionf * self._scale))

        self._description2 = Sprite(self._sprites,
                                   int(SHORTX * self._scale),
                                   int(SHORTY * self._scale),
                                   svg_str_to_pixbuf(
                genblank(int(self._width - (2 * SHORTX * self._scale)),
                          int(SHORTH * self._scale),
                          self._colors)))
        self._description2.set_label_attributes(int(descriptionf * self._scale))

        self._my_canvas = Sprite(self._sprites, 0, 0,
                                gtk.gdk.Pixmap(self._canvas.window,
                                               self._width,
                                               self._height, -1))
        self._my_canvas.set_layer(0)
        self._my_gc = self._my_canvas.images[0].new_gc()

        self._my_canvas.set_layer(1)

        self._clear_screen()

        self._find_starred()
        self.i = 0
        self._show_slide(self.i)

        self._playing = False
        self._rate = 2

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

        self._prev_button = button_factory(
            'go-previous-inactive', _('Prev slide'), self._prev_cb,
            self.toolbar)

        self._next_button = button_factory(
            'go-next', _('Next slide'), self._next_cb,
            self.toolbar)

        separator_factory(self.toolbar)

        self._auto_button = button_factory(
            'media-playlist-repeat', _('Autoplay'), self._autoplay_cb,
            self.toolbar)

        self._slider = slider_factory(
            _('Adjust playback speed'), self._speed_cb, self.toolbar)

        separator_factory(self.toolbar)

        self._save_button = button_factory(
            'transfer-from-text-uri-list', _('Save as HTML'),
            self._save_as_html_cb, self.toolbar)

        if _have_toolbox:
            separator_factory(toolbox.toolbar, False, True)

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
        self._rate = self._slider.value
        self._slider.set_value(int(self._rate + 0.5))

    def _save_as_html_cb(self, button=None):
        self._save_button.set_icon('save-in-progress')
        results = save_html(self._dsobjects, profile.get_nick_name(),
                            self._colors, self._tmp_path)
        html_file = os.path.join(self._tmp_path, 'tmp.html')
        f = open(html_file, 'w')
        f.write(results)
        f.close()

        dsobject = datastore.create()
        dsobject.metadata['title'] = profile.get_nick_name() + ' ' + \
                                     _('Portfolio')
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        dsobject.metadata['mime_type'] = 'text/html'
        dsobject.set_file_path(html_file)
        dsobject.metadata['activity'] = 'org.laptop.WebActivity'
        datastore.write(dsobject)
        dsobject.destroy()

        gobject.timeout_add(250, self._save_button.set_icon,
                            'transfer-from-text-uri-list')
        return

    def _clear_screen(self):
        self._my_gc.set_foreground(
            self._my_gc.get_colormap().alloc_color(self._colors[0]))
        rect = gtk.gdk.Rectangle(0, 0, self._width, self._height)
        self._my_canvas.images[0].draw_rectangle(self._my_gc, True, *rect)
        self.invalt(0, 0, self._width, self._height)

    def _show_slide(self, i):
        self._clear_screen()

        if self._nobjects == 0:
            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')
            self._description.set_label(
                _('Do you have any items in your Journal starred?'))
            self._description.set_layer(1000)
            return

        if self.i == 0:
            self._prev_button.set_icon('go-previous-inactive')
        else:
            self._prev_button.set_icon('go-previous')
        if self.i == self._nobjects - 1:
            self._next_button.set_icon('go-next-inactive')
        else:
            self._next_button.set_icon('go-next')

        pixbuf = None
        media_object = False
        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                self._dsobjects[i].file_path, int(PREVIEWW * self._scale),
                int(PREVIEWH * self._scale))
            media_object = True
        except:
            pixbuf = get_pixbuf_from_journal(self._dsobjects[i], 300, 225)

        if pixbuf is not None:
            if not media_object:
                self._preview.images[0] = pixbuf.scale_simple(
                    int(PREVIEWW * self._scale),
                    int(PREVIEWH * self._scale),
                    gtk.gdk.INTERP_TILES)
                self._full_screen.hide()
                self._preview.set_layer(1000)
            else:
                self._full_screen.images[0] = pixbuf.scale_simple(
                    int(FULLW * self._scale),
                    int(FULLH * self._scale),
                    gtk.gdk.INTERP_TILES)
                self._full_screen.set_layer(1000)
                self._preview.hide()
        else:
            if self._preview is not None:
                self._preview.hide()
                self._full_screen.hide()

        self._title.set_label(self._dsobjects[i].metadata['title'])
        self._title.set_layer(1000)

        if 'description' in self._dsobjects[i].metadata:
            if media_object:
                self._description2.set_label(
                    self._dsobjects[i].metadata['description'])
                self._description2.set_layer(1000)
                self._description.set_label('')
                self._description.hide()
            else:
                self._description.set_label(
                    self._dsobjects[i].metadata['description'])
                self._description.set_layer(1000)
                self._description2.set_label('')
                self._description2.hide()
        else:
            self._description.set_label('')
            self._description.hide()
            self._description2.set_label('')
            self._description2.hide()
            print 'description is None'

    def invalt(self, x, y, w, h):
        ''' Mark a region for refresh '''
        self._canvas.window.invalidate_rect(
            gtk.gdk.Rectangle(int(x), int(y), int(w), int(h)), False)
