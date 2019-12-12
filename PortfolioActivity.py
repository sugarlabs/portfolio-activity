# -*- coding: utf-8 -*-
# Copyright (c) 2011-2013 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301
# USA

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Pango
from gi.repository import PangoCairo

import os
from shutil import copyfile

from math import sqrt, ceil

from sugar3.activity import activity
from sugar3 import profile

from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.activity.widgets import ActivityToolbarButton
from sugar3.activity.widgets import StopButton
from sugar3.graphics.toolbarbox import ToolbarButton

from sugar3.datastore import datastore

from sprites import (Sprites, Sprite)
from utils import (get_path, lighter_color, svg_str_to_pixbuf, svg_rectangle,
                   get_pixbuf_from_journal, genblank, get_hardware, rgb,
                   pixbuf_to_base64, base64_to_pixbuf, get_pixbuf_from_file,
                   parse_comments, get_tablet_mode)
from odp import TurtleODP
from exportpdf import save_pdf
from toolbar_utils import (radio_factory, button_factory, separator_factory,
                           combo_factory, label_factory)
from arecord import Arecord
from aplay import aplay

from gettext import gettext as _

import logging
_logger = logging.getLogger("portfolio-activity")

from sugar3.graphics import style
GRID_CELL_SIZE = style.GRID_CELL_SIZE

import json

from gi.repository import TelepathyGLib
from dbus.service import signal
from dbus.gi_service import ExportedGObject
from sugar3.presence import presenceservice

try:
    from sugar3.presence.wrapper import CollabWrapper
except ImportError:
    from collabwrapper import CollabWrapper


SERVICE = 'org.sugarlabs.PortfolioActivity'
IFACE = SERVICE
PATH = '/org/sugarlabs/PortfolioActivity'

# Size and position of title, preview image, and description
TITLE = [[GRID_CELL_SIZE, 10, 1200 - GRID_CELL_SIZE * 2, 100],
         [GRID_CELL_SIZE, 10, 900 - GRID_CELL_SIZE * 2, 100]]
PREVIEW = [[GRID_CELL_SIZE, 110, 560, 420],
           [180, 110, 560, 420]]
DESC = [[560 + GRID_CELL_SIZE, 110, 560, 420],
        [GRID_CELL_SIZE, 530, 900 - GRID_CELL_SIZE * 2, 300]]
NEW_COMMENT = [[GRID_CELL_SIZE, 530, 1200 - GRID_CELL_SIZE * 2, 100],
               [GRID_CELL_SIZE, 840, 900 - GRID_CELL_SIZE * 2, 100]]
COMMENTS = [[GRID_CELL_SIZE, 640, 1200 - GRID_CELL_SIZE * 2, 250],
            [GRID_CELL_SIZE, 950, 900 - GRID_CELL_SIZE * 2, 240]]

TWO = 0
TEN = 1
THIRTY = 2
SIXTY = 3
UNITS = [_('2 seconds'), _('10 seconds'), _('30 seconds'), _('1 minute')]
UNIT_DICTIONARY = {TWO: (UNITS[TWO], 2),
                   TEN: (UNITS[TEN], 10),
                   THIRTY: (UNITS[THIRTY], 30),
                   SIXTY: (UNITS[SIXTY], 60)}

# sprite layers
DRAG = 6
STAR = 5
TOP = 4
UNDRAG = 3
MIDDLE = 2
BOTTOM = 1
HIDE = 0

OSK_SHIFT = 200


def _get_screen_dpi():
    xft_dpi = Gtk.Settings.get_default().get_property('gtk-xft-dpi')
    dpi = float(xft_dpi / 1024)
    return dpi


class Slide():

    ''' A container for a slide '''

    def __init__(self, owner, uid, colors, title, preview, desc, comment):
        self.active = True
        self.owner = owner
        self.uid = uid
        self.colors = colors
        self.title = title
        self.preview = preview
        self.preview2 = None  # larger version for fullscreen mode
        self.description = desc
        self.comment = comment  # A list of dictionaries
        self.sound = None
        self.dirty = False
        self.fav = True
        self.thumb = None
        self.star = None

    def hide(self):
        if self.star is not None:
            self.star.hide()
        if self.thumb is not None:
            self.thumb.hide()


class PortfolioActivity(activity.Activity):

    ''' Make a slideshow from starred Journal entries. '''

    def __init__(self, handle):
        ''' Initialize the toolbars and the work surface '''
        super(PortfolioActivity, self).__init__(handle)

        self.datapath = get_path(activity, 'instance')
        self._buddies = [profile.get_nick_name()]
        self._colors = profile.get_color().to_string().split(',')
        self._my_colors = self._colors[:]  # Save original colors
        self.initiating = None  # sharing (True) or joining (False)
        self._tablet_mode = get_tablet_mode()

        self._playing = False
        self._first_time = True

        self._set_scale_and_orientation()

        self._set_screen_dpi()
        self._set_xy_wh()

        self.old_cursor = self.get_window().get_cursor()

        self._hw = get_hardware()

        self._setup_toolbars()
        self._setup_canvas()

        self._slides = []
        self._current_slide = 0

        self._thumbnail_mode = False
        self._find_starred()
        self._setup_workspace()

        self._recording = False
        self._arecord = None

        self._keypress = None
        self._selected_spr = None
        self._dead_key = ''
        self._saved_string = ''
        self._startpos = [0, 0]
        self._dragpos = [0, 0]

        self._setup_presence_service()
        self._autoplay_id = None

    def close(self, **kwargs):
        aplay.close()
        activity.Activity.close(self, **kwargs)

    def _set_xy_wh(self):
        orientation = self._orientation
        self._title_wh = [TITLE[orientation][2] * self._scale,
                          TITLE[orientation][3] * self._scale]
        self._title_xy = [TITLE[orientation][0] * self._scale,
                          TITLE[orientation][1] * self._scale]
        self._title_xy[0] = int((self._width - self._title_wh[0]) / 2.)
        self._preview_wh = [PREVIEW[orientation][2] * self._scale,
                            PREVIEW[orientation][3] * self._scale]
        self._preview_xy = [PREVIEW[orientation][0] * self._scale,
                            PREVIEW[orientation][1] * self._scale]
        if orientation == 0:
            self._preview_xy[0] = self._title_xy[0]
        else:
            self._preview_xy[0] = int((self._width - self._preview_wh[0]) / 2.)
        self._desc_wh = [DESC[orientation][2] * self._scale,
                         DESC[orientation][3] * self._scale]
        if orientation == 0:
            self._desc_wh[0] = \
                self._width - self._preview_wh[0] - 2 * self._title_xy[0]
        else:
            self._desc_wh[0] = self._title_wh[0]
        self._desc_xy = [DESC[orientation][0] * self._scale,
                         DESC[orientation][1] * self._scale]
        if orientation == 0:
            self._desc_xy[0] = self._preview_wh[0] + self._title_xy[0]
        else:
            self._desc_xy[0] = self._title_xy[0]
        self._new_comment_wh = [NEW_COMMENT[orientation][2] * self._scale,
                                NEW_COMMENT[orientation][3] * self._scale]
        self._new_comment_xy = [NEW_COMMENT[orientation][0] * self._scale,
                                NEW_COMMENT[orientation][1] * self._scale]
        self._new_comment_xy[0] = self._title_xy[0]
        self._new_comment_xy[1] = self._desc_xy[1] + self._desc_wh[1]
        self._comment_wh = [COMMENTS[orientation][2] * self._scale,
                            COMMENTS[orientation][3] * self._scale]
        self._comment_xy = [COMMENTS[orientation][0] * self._scale,
                            COMMENTS[orientation][1] * self._scale]
        self._comment_xy[0] = self._title_xy[0]
        self._comment_xy[1] = self._new_comment_xy[1] + self._new_comment_wh[1]

    def _set_screen_dpi(self):
        dpi = _get_screen_dpi()
        font_map_default = PangoCairo.font_map_get_default()
        font_map_default.set_resolution(dpi)

    def _fixed_resize_cb(self, widget=None, rect=None):
        ''' If a toolbar opens or closes, we need to resize the vbox
        holding out scrolling window. '''
        self.vbox.set_size_request(rect.width, rect.height)

    def _setup_canvas(self):
        ''' Create a canvas '''

        self.fixed = Gtk.Fixed()
        self.fixed.connect('size-allocate', self._fixed_resize_cb)
        self.fixed.show()
        self.set_canvas(self.fixed)

        self.vbox = Gtk.VBox(False, 0)
        self.vbox.set_size_request(Gdk.Screen.width(), Gdk.Screen.height())
        self.fixed.put(self.vbox, 0, 0)
        self.vbox.show()

        self._canvas = Gtk.DrawingArea()
        self._canvas.set_size_request(int(Gdk.Screen.width()),
                                      int(Gdk.Screen.height()))
        self._canvas.show()
        self.show_all()
        self.vbox.pack_end(self._canvas, True, True, 0)
        self.vbox.show()

        self._canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self._canvas.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
        self._canvas.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        self._canvas.add_events(Gdk.EventMask.KEY_PRESS_MASK)
        self._canvas.connect('draw', self._draw_cb)
        self._canvas.connect('button-press-event', self._button_press_cb)
        self._canvas.connect('button-release-event', self._button_release_cb)
        self._canvas.connect('motion-notify-event', self._mouse_move_cb)
        self._canvas.connect('key-press-event', self._keypress_cb)
        Gdk.Screen.get_default().connect('size-changed', self._configure_cb)

        self._canvas.grab_focus()

    def _set_scale_and_orientation(self):
        self._width = Gdk.Screen.width()
        self._height = Gdk.Screen.height()
        if self._width > self._height:
            self._scale = Gdk.Screen.height() / 900.
            self._orientation = 0
        else:
            self._scale = Gdk.Screen.height() / 1200.
            self._orientation = 1

    def _configure_cb(self, event):
        self._my_canvas.hide()
        self._title.hide()
        self._description.hide()
        self._comment.hide()
        self._new_comment.hide()

        self._set_scale_and_orientation()

        self.vbox.set_size_request(Gdk.Screen.width(), Gdk.Screen.height())
        self.vbox.show()
        self._canvas.set_size_request(int(Gdk.Screen.width()),
                                      int(Gdk.Screen.height()))
        self._canvas.show()
        self._set_xy_wh()

        self._configured_sprites()  # Some sprites are sized to screen
        self._my_canvas.set_layer(BOTTOM)
        self._clear_screen()
        if self._thumbnail_mode:
            self._thumbs_cb()
        else:
            self._show_slide()

    def _setup_workspace(self):
        ''' Prepare to render the datastore entries. '''

        # Use the lighter color for the text background
        if lighter_color(self._colors) == 0:
            tmp = self._colors[0]
            self._colors[0] = self._colors[1]
            self._colors[1] = tmp

        if self._hw[0:2] == 'xo':
            self.title_size = 18
            self.desc_size = 12
        else:
            self.title_size = int(36 * self._scale)
            self.desc_size = int(24 * self._scale)

        # Generate the sprites we'll need...
        self._sprites = Sprites(self._canvas)

        if self._nobjects == 0:
            star_size = GRID_CELL_SIZE
        else:
            star_size = int(150. / int(ceil(sqrt(self._nobjects))))
        self._fav_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'favorite-on.svg'), star_size, star_size)
        self._unfav_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'favorite-off.svg'), star_size, star_size)

        self.record_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'media-audio.svg'), GRID_CELL_SIZE, GRID_CELL_SIZE)
        self.recording_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(
                activity.get_bundle_path(),
                'icons',
                'media-audio-recording.svg'),
            GRID_CELL_SIZE,
            GRID_CELL_SIZE)
        self.playback_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'speaker-100.svg'), GRID_CELL_SIZE, GRID_CELL_SIZE)
        self.playing_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'speaker-0.svg'), GRID_CELL_SIZE, GRID_CELL_SIZE)

        self._record_button = Sprite(self._sprites, 0, 0, self.record_pixbuf)
        self._record_button.set_layer(DRAG)
        self._record_button.type = 'record'

        self._playback_button = Sprite(self._sprites, 0, 0,
                                       self.playback_pixbuf)
        self._playback_button.type = 'noplay'
        self._playback_button.hide()

        self.prev_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'go-previous.svg'), GRID_CELL_SIZE, GRID_CELL_SIZE)
        self.next_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'go-next.svg'), GRID_CELL_SIZE, GRID_CELL_SIZE)
        self.prev_off_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(
                activity.get_bundle_path(),
                'icons',
                'go-previous-inactive.svg'),
            GRID_CELL_SIZE,
            GRID_CELL_SIZE)
        self.next_off_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(
                activity.get_bundle_path(),
                'icons',
                'go-next-inactive.svg'),
            GRID_CELL_SIZE,
            GRID_CELL_SIZE)

        self._prev = Sprite(self._sprites, 0, 0, self.prev_off_pixbuf)
        self._prev.set_layer(DRAG)
        self._prev.type = 'prev'

        self._next = Sprite(self._sprites, 0, 0, self.next_pixbuf)
        self._next.set_layer(DRAG)
        self._next.type = 'next'

        self._help = Sprite(
            self._sprites, 0, 0, GdkPixbuf.Pixbuf.new_from_file_at_size(
                os.path.join(
                    activity.get_bundle_path(), 'help.png'), int(
                    self._preview_wh[0]), int(
                    self._preview_wh[1])))
        self._help.hide()

        self._preview = Sprite(self._sprites,
                               0, 0,
                               svg_str_to_pixbuf(genblank(
                                   int(self._preview_wh[0]),
                                   int(self._preview_wh[1]),
                                   self._colors)))

        self._configured_sprites()  # Some sprites are sized to screen

        self._clear_screen()

        self.i = 0
        self._show_slide()

        self._playing = False
        self._rate = 10

    def _configured_sprites(self):
        ''' Some sprites are sized or positioned based on screen
        configuration '''

        self._preview.move((int(self._preview_xy[0]),
                            int(self._preview_xy[1])))
        self._help.move((int(self._preview_xy[0]),
                         int(self._preview_xy[1])))
        self._record_button.move((self._width - GRID_CELL_SIZE,
                                  self._title_wh[1]))
        self._playback_button.move((self._width - GRID_CELL_SIZE,
                                    self._title_wh[1] + GRID_CELL_SIZE))
        self._prev.move((0, int((self._height - GRID_CELL_SIZE) / 2)))
        self._next.move((self._width - GRID_CELL_SIZE,
                         int((self._height - GRID_CELL_SIZE) / 2)))
        self._title = Sprite(
            self._sprites, int(
                self._title_xy[0]), int(
                self._title_xy[1]), svg_str_to_pixbuf(
                genblank(
                    self._title_wh[0], self._title_wh[1], self._colors)))
        self._title.set_label_attributes(self.title_size, rescale=False)
        self._title.type = 'title'

        self._description = Sprite(self._sprites,
                                   int(self._desc_xy[0]),
                                   int(self._desc_xy[1]),
                                   svg_str_to_pixbuf(
                                       genblank(int(self._desc_wh[0]),
                                                int(self._desc_wh[1]),
                                                self._colors)))
        self._description.set_label_attributes(self.desc_size,
                                               horiz_align="left",
                                               rescale=False, vert_align="top")
        m = int(self.desc_size / 2)
        self._description.set_margins(l=m, t=m, r=m, b=m)
        self._description.type = 'description'

        self._comment = Sprite(self._sprites,
                               int(self._comment_xy[0]),
                               int(self._comment_xy[1]),
                               svg_str_to_pixbuf(
                                   genblank(int(self._comment_wh[0]),
                                            int(self._comment_wh[1]),
                                            self._colors)))
        self._comment.set_label_attributes(int(self.desc_size * 0.67),
                                           vert_align="top",
                                           horiz_align="left",
                                           rescale=False)
        self._comment.set_margins(l=m, t=m, r=m, b=m)
        self._new_comment = Sprite(self._sprites,
                                   int(self._new_comment_xy[0]),
                                   int(self._new_comment_xy[1]),
                                   svg_str_to_pixbuf(
                                       genblank(int(self._new_comment_wh[0]),
                                                int(self._new_comment_wh[1]),
                                                self._colors)))
        self._new_comment.set_label_attributes(self.desc_size,
                                               horiz_align="left",
                                               vert_align="top", rescale=False)
        self._new_comment.type = 'comment'
        self._new_comment.set_label(_('Enter comments here.'))

        self._my_canvas = Sprite(
            self._sprites, 0, 0, svg_str_to_pixbuf(genblank(
                self._width, self._height, (self._colors[0],
                                            self._colors[0]))))
        self._my_canvas.set_layer(BOTTOM)
        self._my_canvas.type = 'background'

    def _setup_toolbars(self):
        ''' Setup the toolbars. '''

        self.max_participants = 4  # sharing

        toolbox = ToolbarBox()

        # Activity toolbar
        activity_button_toolbar = ActivityToolbarButton(self)

        toolbox.toolbar.insert(activity_button_toolbar, 0)
        activity_button_toolbar.show()

        self.set_toolbar_box(toolbox)
        toolbox.show()
        self.toolbar = toolbox.toolbar

        adjust_toolbar = Gtk.Toolbar()
        adjust_toolbar_button = ToolbarButton(
            label=_('Adjust'),
            page=adjust_toolbar,
            icon_name='preferences-system')
        adjust_toolbar.show_all()
        adjust_toolbar_button.show()

        toolbox.toolbar.insert(adjust_toolbar_button, -1)

        button_factory('view-fullscreen', self.toolbar,
                       self.do_fullscreen_cb, tooltip=_('Fullscreen'),
                       accelerator='<Alt>Return')

        self._auto_button = button_factory(
            'media-playback-start', self.toolbar,
            self._autoplay_cb, tooltip=_('Autoplay'))

        label = label_factory(adjust_toolbar, _('Adjust playback speed'),
                              width=200)
        label.show()

        separator_factory(adjust_toolbar, False, False)

        self._unit_combo = combo_factory(UNITS,
                                         adjust_toolbar,
                                         self._unit_combo_cb,
                                         default=UNITS[TEN],
                                         tooltip=_('Adjust playback speed'))
        self._unit_combo.show()

        separator_factory(adjust_toolbar)

        button_factory('system-restart',
                       adjust_toolbar,
                       self._rescan_cb,
                       tooltip=_('Refresh'))

        separator_factory(self.toolbar)

        self._slide_button = radio_factory('slide-view',
                                           self.toolbar,
                                           self._slides_cb,
                                           group=None,
                                           tooltip=_('Slide view'))

        self._thumb_button = radio_factory('thumbs-view',
                                           self.toolbar,
                                           self._thumbs_cb,
                                           tooltip=_('Thumbnail view'),
                                           group=self._slide_button)

        separator_factory(self.toolbar)
        self._save_pdf = button_factory('save-as-pdf',
                                        self.toolbar,
                                        self._save_as_pdf_cb,
                                        tooltip=_('Save as PDF'))

        self._save_odp = button_factory('save-as-odp',
                                        self.toolbar,
                                        self._save_as_odp_cb,
                                        tooltip=_('Save as presentation'))

        separator_factory(toolbox.toolbar, True, False)

        stop_button = StopButton(self)
        stop_button.props.accelerator = '<Ctrl>q'
        toolbox.toolbar.insert(stop_button, -1)
        stop_button.show()

        toolbox.toolbar.show_all()

    def _destroy_cb(self, win, event):
        ''' Clean up on the way out. '''
        Gtk.main_quit()

    def _thumb_to_slide(self, spr):
        if spr is None:
            return None
        for slide in self._slides:
            if slide.thumb == spr:
                return slide
        return None

    def _star_to_slide(self, spr):
        if spr is None:
            return None
        for slide in self._slides:
            if slide.star == spr:
                return slide
        return None

    def _uid_to_slide(self, uid):
        for slide in self._slides:
            if slide.uid == uid:
                return slide
        return None

    def _make_star(self, slide):
        slide.star = Sprite(self._sprites, 0, 0, self._fav_pixbuf)
        slide.star.type = 'star'
        slide.star.set_layer(STAR)
        slide.fav = True

    def _find_starred(self):
        ''' Find all the _stars in the Journal. '''
        for slide in self._slides:
            slide.active = False
        self.dsobjects, self._nobjects = datastore.find({'keep': '1'})
        for dsobj in self.dsobjects:
            slide = self._uid_to_slide(dsobj.object_id)
            owner = self._buddies[0]
            title = ''
            desc = ''
            comment = []
            preview = None
            if hasattr(dsobj, 'metadata'):
                if 'title' in dsobj.metadata:
                    title = dsobj.metadata['title']
                if 'description' in dsobj.metadata:
                    desc = dsobj.metadata['description']
                if 'comments' in dsobj.metadata:
                    try:
                        comment = json.loads(dsobj.metadata['comments'])
                        _logger.debug(comment)
                    except:
                        comment = []
                if 'mime_type' in dsobj.metadata and \
                   dsobj.metadata['mime_type'][0:5] == 'image':
                    preview = get_pixbuf_from_file(
                        dsobj.file_path,
                        int(PREVIEW[self._orientation][2] * self._scale),
                        int(PREVIEW[self._orientation][3] * self._scale))
                elif 'preview' in dsobj.metadata:
                    preview = get_pixbuf_from_journal(dsobj, 300, 225)
            else:
                _logger.debug('dsobj has no metadata')

            if slide is None:
                self._slides.append(Slide(owner,
                                          dsobj.object_id,
                                          self._colors,
                                          title,
                                          preview,
                                          desc,
                                          comment))
            else:
                slide.title = title
                slide.preview = preview
                slide.description = desc
                slide.comment = comment
                slide.active = True
                slide.fav = True
                if slide.star is not None:
                    slide.star.hide()
                if slide.thumb is not None:
                    slide.thumb.hide()

    def _rescan_cb(self, button=None):
        ''' Rescan the Journal for changes in starred items. '''
        if self.initiating is not None and not self.initiating:
            return
        if self.initiating:
            self._send_event('R', {"data": 'rescanning'})
        self._help.hide()
        self._find_starred()
        self.i = 0
        if self.initiating:
            self._share_slides()
        if self._thumbnail_mode:
            self._thumbs_cb()
        else:
            self._show_slide()

    def _first_cb(self, button=None):
        self.i = 0
        self._show_slide(direction=-1)

    def _prev_cb(self, button=None):
        ''' The previous button has been clicked; goto previous slide. '''
        if self.i > 0:
            self.i -= 1
            self._show_slide(direction=-1)

    def _next_cb(self, button=None):
        ''' The next button has been clicked; goto next slide. '''
        if self.i < self._nobjects - 1:
            self.i += 1
            self._show_slide()

    def _last_cb(self, button=None):
        self.i = self._nobjects - 1
        self._show_slide()

    def _autoplay_cb(self, button=None):
        ''' The autoplay button has been clicked; step through slides. '''
        if self._playing:
            self._stop_autoplay()
        else:
            if self._thumbnail_mode:
                self._thumbnail_mode = False
                self.i = self._current_slide
            if self._first_time:
                self.i -= 1
                self._first_time = False
            self._playing = True
            self._auto_button.set_icon_name('media-playback-pause')
            self._autoplay_timeout()

    def _stop_autoplay(self):
        ''' Stop autoplaying. '''
        self._playing = False
        self._auto_button.set_icon_name('media-playback-start')
        if self._autoplay_id is not None:
            GLib.source_remove(self._autoplay_id)
            self._autoplay_id = None

    def _autoplay_timeout(self):
        ''' Show a slide and then call oneself with a timeout. '''
        self.i += 1
        if self.i == self._nobjects:
            self.i = 0
        self._show_slide()
        self._autoplay_id = GLib.timeout_add(int(self._rate * 1000),
                                             self._autoplay_timeout)

    def _save_as_pdf_cb(self, button=None):
        ''' Export an PDF version of the slideshow to the Journal. '''
        if self.initiating is not None and not self.initiating:
            nick = self._buddies[-1]
        else:
            nick = profile.get_nick_name()
        _logger.debug('saving to PDF...')
        if 'description' in self.metadata:
            tmp_file = save_pdf(self, nick,
                                description=self.metadata['description'])
        else:
            tmp_file = save_pdf(self, profile.get_nick_name())

        dsobject = datastore.create()
        dsobject.metadata['title'] = '%s %s' % (nick, _('Portfolio'))
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        dsobject.metadata['mime_type'] = 'application/pdf'
        dsobject.set_file_path(tmp_file)
        dsobject.metadata['activity'] = 'org.laptop.sugar3.ReadActivity'
        datastore.write(dsobject)
        dsobject.destroy()
        return

    def _clear_screen(self):
        ''' Clear the screen to the darker of the two XO colors. '''
        for slide in self._slides:
            slide.hide()
        self._title.hide()
        self._preview.hide()
        self._description.hide()
        self._comment.hide()
        self._new_comment.hide()

        # Reset drag settings
        self._press = None
        self._release = None
        self._dragpos = [0, 0]
        self._total_drag = [0, 0]
        self.last_spr_moved = None

    def _show_slide(self, direction=1):
        ''' Display a title, preview image, and decription for slide
        i. Play an audio note if there is one recorded for this
        object. '''
        self._clear_screen()

        if self._nobjects == 0:
            self._prev.set_image(self.prev_off_pixbuf)
            self._next.set_image(self.next_off_pixbuf)
            self._description.set_label(
                _('Do you have any items in your Journal starred?'))
            self._help.set_layer(TOP)
            self._description.set_layer(MIDDLE)
            self._prev.hide()
            self._next.hide()
            self._record_button.hide()
            self._playback_button.hide()
            return

        slide = self._slides[self.i]
        # Skip slide if unstarred or inactive
        if not slide.active or not slide.fav:
            counter = 0
            while not slide.active or not slide.fav:
                self.i += direction
                if self.i < 0:
                    self.i = len(self._slides) - 1
                elif self.i > len(self._slides) - 1:
                    self.i = 0
                counter += 1
                if counter == len(self._slides):
                    _logger.debug('No _stars: nothing to show')
                    return
                slide = self._slides[self.i]

        if self.i == 0:
            self._prev.set_image(self.prev_off_pixbuf)
        else:
            self._prev.set_image(self.prev_pixbuf)
        if self.i > self._nobjects - 2:
            self._next.set_image(self.next_off_pixbuf)
        else:
            self._next.set_image(self.next_pixbuf)
        self._prev.set_layer(DRAG)
        self._next.set_layer(DRAG)

        pixbuf = slide.preview

        if pixbuf is not None:
            self._preview.set_shape(pixbuf.scale_simple(
                int(PREVIEW[self._orientation][2] * self._scale),
                int(PREVIEW[self._orientation][3] * self._scale),
                GdkPixbuf.InterpType.NEAREST))
            self._preview.set_layer(MIDDLE)
        else:
            if self._preview is not None:
                self._preview.hide()

        self._title.set_label(slide.title)
        self._title.set_layer(MIDDLE)

        if len(slide.description) == 0:
            self._description.set_label(_('This project is about...'))
        else:
            self._description.set_label(slide.description)
        self._description.set_layer(MIDDLE)

        self._comment.set_label(parse_comments(slide.comment))
        self._comment.set_layer(MIDDLE)

        self._new_comment.set_layer(MIDDLE)

        if self.initiating is None or self.initiating:
            if slide.sound is None:
                slide.sound = self._search_for_audio_note(slide.uid)
            if slide.sound is not None:
                if self._playing:
                    _logger.debug('Playing audio note')
                    aplay.play(slide.sound.file_path)
                self._playback_button.set_image(self.playback_pixbuf)
                self._playback_button.type = 'play'
                self._playback_button.set_layer(DRAG)
            else:
                self._playback_button.hide()
                self._playback_button.type = 'noplay'
            self._record_button.set_image(self.record_pixbuf)
        else:
            self._record_button.hide()
            self._playback_button.hide()

    def _slides_cb(self, button=None):
        if self._thumbnail_mode:
            self._thumbnail_mode = False
        self.i = self._current_slide
        self._record_button.set_layer(DRAG)
        self._playback_button.set_layer(DRAG)
        self._show_slide()

    def _thumbs_cb(self, button=None):
        ''' Toggle between thumbnail view and slideshow view. '''
        if not self._thumbnail_mode:
            self._thumbnail_mode = True
        self._first_time = True
        self._show_thumbs()
        return False

    def _count_active(self):
        count = 0
        for slide in self._slides:
            if slide.active:
                count += 1
        return count

    def _show_thumbs(self):
        self._stop_autoplay()
        self._current_slide = self.i
        self._clear_screen()

        self._record_button.hide()
        self._playback_button.hide()
        self._prev.hide()
        self._next.hide()

        n = int(ceil(sqrt(self._count_active())))
        if n > 0:
            w = int(self._width / n)
        else:
            w = self._width
        h = int(w * 0.75)  # maintain 4:3 aspect ratio
        x_off = int((self._width - n * w) / 2)
        x = x_off
        y = 0
        for slide in self._slides:
            if not slide.active:
                continue
            self._show_thumb(slide, x, y, w, h)
            x += w
            if x + w > self._width:
                x = x_off
                y += h
        self.i = 0  # Reset position in slideshow to the beginning

    def _show_thumb(self, slide, x, y, w, h):
        ''' Display a preview image and title as a thumbnail. '''

        # Is size has changed, regenerate the thumbnail
        if slide.thumb is not None:
            sw, sh = slide.thumb.get_dimensions()
            if sw == w and sh == h:
                slide.thumb.move((x, y))
            else:
                slide.thumb.hide()
                slide.thumb = None
        if slide.thumb is None:
            if slide.preview is not None:
                pixbuf_thumb = slide.preview.scale_simple(
                    int(w), int(h), GdkPixbuf.InterpType.TILES)
            else:
                pixbuf_thumb = svg_str_to_pixbuf(genblank(int(w), int(h),
                                                          self._colors))
            slide.thumb = Sprite(self._sprites, x, y, pixbuf_thumb)
            # Add a border
            slide.thumb.set_image(svg_str_to_pixbuf(
                svg_rectangle(int(w), int(h), slide.colors)), i=1)
        slide.thumb.set_layer(TOP)
        if slide.star is None:
            self._make_star(slide)
        slide.star.set_layer(STAR)
        slide.star.move((x, y))

    def _draw_cb(self, canvas, cr):
        self._sprites.redraw_sprites(cr=cr)

    def write_file(self, file_path):
        ''' Clean up '''
        if self.initiating is not None and not self.initiating:
            _logger.debug('I am a joiner, so I am not saving.')
            return

        self._save_changes_cb()
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            os.remove(os.path.join(self.datapath, 'output.ogg'))

    def do_fullscreen_cb(self, button):
        ''' Hide the sugar3 toolbars. '''
        self.fullscreen()

    def _text_focus_out_cb(self, widget=None, event=None):
        bounds = self.text_buffer.get_bounds()
        text = self.text_buffer.get_text(bounds[0], bounds[1], True)
        self._selected_spr.set_label(text)
        self._saved_string = self._selected_spr.labels[0]

    def _button_press_cb(self, win, event):
        ''' The mouse button was pressed. Is it on a sprite? '''
        if self._nobjects == 0:
            return
        x, y = list(map(int, event.get_coords()))

        self._dragpos = [x, y]
        self._total_drag = [0, 0]

        spr = self._sprites.find_sprite((x, y))
        if spr is not None:
            self._startpos = spr.get_xy()
        self._press = None
        self._release = None

        # Are we clicking on a title or description or comment?
        if spr.type in ['title', 'description', 'comment']:
            if spr == self._selected_spr:
                return True
            elif self._selected_spr is not None:
                self._unselect()
            self._selected_spr = spr
            self._saved_string = spr.labels[0]
            if spr.type == 'description':
                if self.initiating is None or self.initiating:
                    label = self._selected_spr.labels[0]
                    self._selected_spr.set_label(label)
                else:
                    self._selected_spr = None
                    return True
                self._selected_spr.set_label(label)
                if not hasattr(self, 'desc_entry'):
                    self.desc_entry = Gtk.TextView()
                    self.desc_entry.set_wrap_mode(Gtk.WrapMode.WORD)
                    self.desc_entry.set_pixels_above_lines(0)
                    self.desc_entry.set_size_request(self._desc_wh[0],
                                                     self._desc_wh[1])
                    rgba = Gdk.RGBA()
                    rgba.red, rgba.green, rgba.blue = rgb(self._colors[1])
                    rgba.alpha = 1.
                    self.desc_entry.override_background_color(
                        Gtk.StateFlags.NORMAL, rgba)
                    font_desc = Pango.font_description_from_string(
                        str(self.desc_size))
                    self.desc_entry.modify_font(font_desc)
                    self.fixed.put(self.desc_entry, 0, 0)
                self.text_entry = self.desc_entry
                self.text_buffer = self.desc_entry.get_buffer()
                self.desc_entry.show()
            elif spr.type == 'title':
                if self.initiating is None or self.initiating:
                    label = self._selected_spr.labels[0]
                    self._selected_spr.set_label(label)
                else:
                    self._selected_spr = None
                    return True
                if not hasattr(self, 'title_entry'):
                    self.title_entry = Gtk.TextView()
                    self.title_entry.set_justification(
                        Gtk.Justification.CENTER)
                    self.title_entry.set_pixels_above_lines(1)
                    rgba = Gdk.RGBA()
                    rgba.red, rgba.green, rgba.blue = rgb(self._colors[1])
                    rgba.alpha = 1.
                    self.title_entry.override_background_color(
                        Gtk.StateFlags.NORMAL, rgba)
                    font_desc = Pango.font_description_from_string(
                        str(self.title_size))
                    self.title_entry.modify_font(font_desc)
                    self.fixed.put(self.title_entry, 0, 0)
                self.text_entry = self.title_entry
                self.text_buffer = self.title_entry.get_buffer()
                self.text_buffer.connect('insert-text', self._insert_text_cb)
                self.title_entry.show()
            elif spr.type == 'comment':
                self._selected_spr.set_label('')
                self._saved_string = spr.labels[0]
                if not hasattr(self, 'comment_entry'):
                    self.comment_entry = Gtk.TextView()
                    self.comment_entry.set_wrap_mode(Gtk.WrapMode.WORD)
                    self.comment_entry.set_pixels_above_lines(0)
                    self.comment_entry.set_size_request(
                        self._new_comment_wh[0], self._new_comment_wh[1])
                    rgba = Gdk.RGBA()
                    rgba.red, rgba.green, rgba.blue = rgb(self._colors[1])
                    rgba.alpha = 1.
                    self.comment_entry.override_background_color(
                        Gtk.StateFlags.NORMAL, rgba)
                    font_desc = Pango.font_description_from_string(
                        str(self.desc_size))
                    self.comment_entry.modify_font(font_desc)
                    self.fixed.put(self.comment_entry, 0, 0)
                self.text_entry = self.comment_entry
                self.text_buffer = self.comment_entry.get_buffer()
                self.text_buffer.connect('insert-text', self._insert_text_cb)
                self.comment_entry.show()
            self.text_buffer.set_text(self._saved_string)

            # Clear the label while the text_entry is visible
            spr.set_label('')
            w = spr.label_safe_width()
            h = spr.label_safe_height()

            if spr.type == 'comment':
                if self._tablet_mode:
                    self._OSK_shift(spr, -OSK_SHIFT)
            bx, by = spr.get_xy()
            mx, my = spr.label_left_top()
            self.text_entry.set_size_request(w, h)
            self.fixed.move(self.text_entry, bx + mx, by + my * 2)
            self.text_entry.connect('focus-out-event',
                                    self._text_focus_out_cb)
            self.text_entry.grab_focus()
            self.fixed.show()
        else:
            self._unselect()

        # Are we clicking on a button?
        if spr.type == 'next':
            self._next_cb()
            return True
        elif spr.type == 'prev':
            self._prev_cb()
            return True
        elif spr.type == 'record':
            self._record_cb()
            return True
        elif spr.type == 'recording':
            self._record_cb()
            return True
        elif spr.type == 'play':
            self._playback_recording_cb()
            return True

        # Are we clicking on a star?
        if spr.type == 'star':
            spr.set_shape(self._unfav_pixbuf)
            spr.type = 'unstar'
            slide = self._star_to_slide(spr)
            slide.fav = False
            if self.initiating:
                self._send_star(slide.uid, False)
        elif spr.type == 'unstar':
            spr.set_shape(self._fav_pixbuf)
            spr.type = 'star'
            slide = self._star_to_slide(spr)
            slide.fav = True
            if self.initiating:
                self._send_star(slide.uid, True)

        # Are we clicking on a thumbnail?
        slide = self._thumb_to_slide(spr)
        if slide is None:
            return False

        self.last_spr_moved = spr
        self._press = spr
        self._press.set_layer(DRAG)
        slide.star.set_layer(DRAG + 1)
        return False

    def _OSK_shift(self, spr, dy):
        ''' Move some sprites when OSK appears/disappears '''
        dy *= self._scale
        spr.move_relative((0, dy))
        self._title.move_relative((0, dy))
        self._preview.move_relative((0, dy))
        self._description.move_relative((0, dy))

    def _mouse_move_cb(self, win, event):
        ''' Drag a thumbnail with the mouse. '''
        spr = self._press
        if spr is None:
            self._dragpos = [0, 0]
            return False
        win.grab_focus()
        x, y = list(map(int, event.get_coords()))
        dx = x - self._dragpos[0]
        dy = y - self._dragpos[1]
        spr.move_relative([dx, dy])
        # Also move the star
        slide = self._thumb_to_slide(spr)
        if slide is not None:
            slide.star.move_relative([dx, dy])
        self._dragpos = [x, y]
        self._total_drag[0] += dx
        self._total_drag[1] += dy
        return False

    def _button_release_cb(self, win, event):
        ''' Button event is used to swap slides or goto next slide. '''
        win.grab_focus()
        self._dragpos = [0, 0]
        x, y = list(map(int, event.get_coords()))

        if self._press is None:
            return

        if self._thumbnail_mode:
            press_slide = self._thumb_to_slide(self._press)
            # Drop the dragged thumbnail below the other thumbnails so
            # that you can find the thumbnail beneath it...
            self._press.set_layer(UNDRAG)
            if press_slide is not None:
                press_slide.star.set_layer(STAR)
            spr = self._sprites.find_sprite((x, y))
            self._press.set_layer(TOP)  # and then restore press to top layer

            if press_slide is not None:
                self._release = spr
                # If we found a thumbnail
                # ...and it is the one we dragged, jump to that slide.
                if self._press == self._release:
                    if self._total_drag[0] * self._total_drag[0] + \
                       self._total_drag[1] * self._total_drag[1] < 200:
                        self.i = self._slides.index(press_slide)
                        self._current_slide = self.i
                        self._slide_button.set_active(True)
                    else:  # TODO: test for dragged to beginning
                        i = self._slides.index(press_slide)
                        n = len(self._slides) - 1
                        press_slide.thumb.move(self._startpos)
                        press_slide.star.move(self._startpos)
                        if self._total_drag[1] > 0:
                            while i < n:
                                self._swap_slides(i, i + 1)
                                i += 1
                        else:
                            while i > 0:
                                self._swap_slides(i, i - 1)
                                i -= 1
                # ...and it is not the one we dragged, swap their positions.
                else:
                    # Could have released on top of a star or a thumbnail
                    if self._release.type in ['star', 'unstar']:
                        release_slide = self._star_to_slide(self._release)
                    else:
                        release_slide = self._thumb_to_slide(self._release)
                    press_slide.thumb.move(self._startpos)
                    press_slide.star.move(self._startpos)
                    self._swap_slides(self._slides.index(press_slide),
                                      self._slides.index(release_slide))
        self._press = None
        self._release = None
        return False

    def _insert_text_cb(self, textbuffer, textiter, text, length):
        if '\12' in text:
            self._unselect()

    def _swap_slides(self, i, j):
        ''' Swap order and x, y position of two slides '''
        tmp = self._slides[i]
        self._slides[i] = self._slides[j]
        self._slides[j] = tmp
        xi, yi = self._slides[i].thumb.get_xy()
        xj, yj = self._slides[j].thumb.get_xy()
        self._slides[i].thumb.move((xj, yj))
        self._slides[i].star.move((xj, yj))
        self._slides[j].thumb.move((xi, yi))
        self._slides[j].star.move((xi, yi))

    def _unit_combo_cb(self, arg=None):
        ''' Read value of predefined conversion factors from combo box '''
        if hasattr(self, '_unit_combo'):
            active = self._unit_combo.get_active()
            if active in UNIT_DICTIONARY:
                self._rate = UNIT_DICTIONARY[active][1]

    def _record_cb(self, button=None, cb=None):
        ''' Start/stop audio recording '''
        if self.initiating is not None and not self.initiating:
            return
        if self._arecord is None:
            self._arecord = Arecord(self)
        if self.i < 0 or self.i > len(self._slides) - 1:
            _logger.debug('bad slide index %d' % (self.i))
            return
        else:
            _logger.debug('slide #%d' % (self.i))
        if self._recording:  # Was recording, so stop (and save?)
            _logger.debug('recording...True. Preparing to save.')
            self._arecord.stop_recording_audio()
            self._recording = False
            self._record_button.set_image(self.record_pixbuf)
            self._record_button.type = 'record'
            self._record_button.set_layer(DRAG)
            self._playback_button.set_image(self.playback_pixbuf)
            self._playback_button.type = 'play'
            self._playback_button.set_layer(DRAG)
            # Autosave if there was not already a recording
            _logger.debug('Autosaving recording')
            self.busy()
            GLib.timeout_add(100, self._is_record_complete_timeout, cb)
        else:  # Wasn't recording, so start
            _logger.debug('recording...False. Start recording.')
            self._record_button.set_image(self.recording_pixbuf)
            self._record_button.type = 'recording'
            self._record_button.set_layer(DRAG)
            self._arecord.record_audio()
            self._recording = True

    def _is_record_complete_timeout(self, cb=None):
        if not self._arecord.is_complete():
            return True  # call back later
        self._save_recording()
        self.unbusy()
        if cb is not None:
            cb()
        return False  # do not call back

    def _playback_recording_cb(self, button=None):
        ''' Play back current recording '''
        _logger.debug('Playback current recording from output.ogg...')
        if self.i < 0 or self.i > len(self._slides) - 1:
            _logger.debug('bad slide index %d' % (self.i))
            return
        if self._slides[self.i].sound is None:
            _logger.debug('slide %d has no sound' % (self.i))
            return
        self._playback_button.set_image(self.playing_pixbuf)
        self._playback_button.set_layer(DRAG)
        self._playback_button.type = 'playing'
        GLib.timeout_add(1000, self._playback_button_reset)
        aplay.play(self._slides[self.i].sound.file_path)

    def _playback_button_reset(self):
        self._playback_button.set_image(self.playback_pixbuf)
        self._playback_button.set_layer(DRAG)
        self._playback_button.type = 'play'

    def _save_recording(self):
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            _logger.debug('Saving recording to Journal...')
            slide = self._slides[self.i]
            copyfile(os.path.join(self.datapath, 'output.ogg'),
                     os.path.join(self.datapath, '%s.ogg' % (slide.uid)))
            dsobject = self._search_for_audio_note(slide.uid)
            if dsobject is None:
                dsobject = datastore.create()
            if dsobject is not None:
                _logger.debug(slide.title)
                slide.sound = dsobject
                dsobject.metadata['title'] = _('audio note for %s') % \
                    (slide.title)
                dsobject.metadata['icon-color'] = \
                    profile.get_color().to_string()
                dsobject.metadata['tags'] = slide.uid
                dsobject.metadata['mime_type'] = 'audio/ogg'
                dsobject.set_file_path(
                    os.path.join(self.datapath, '%s.ogg' % (slide.uid)))
                datastore.write(dsobject)
                dsobject.destroy()
        else:
            _logger.debug('Nothing to save...')
        return

    def _search_for_audio_note(self, obj_id):
        ''' Look to see if there is already a sound recorded for this
        dsobject '''
        if self.initiating is not None and not self.initiating:
            return
        dsobjects, nobjects = datastore.find({'mime_type': ['audio/ogg']})
        # Look for tag that matches the target object id
        for dsobject in dsobjects:
            if 'tags' in dsobject.metadata and \
               obj_id in dsobject.metadata['tags']:
                _logger.debug('Found audio note')
                return dsobject
        return None

    def _save_changes_cb(self, button=None):
        ''' Find the object in the datastore and write out the changes
        to the decriptions and titles. '''
        if self.initiating is not None and not self.initiating:
            _logger.debug('skipping write (%s)' % (str(self.initiating)))
            return
        for slide in self._slides:
            if not slide.dirty:
                continue
            _logger.debug('%d is dirty... writing' % (
                self._slides.index(slide)))
            jobject = datastore.get(slide.uid)
            jobject.metadata['description'] = slide.description
            jobject.metadata['comments'] = json.dumps(slide.comment)
            jobject.metadata['title'] = slide.title
            datastore.write(jobject,
                            update_mtime=False,
                            reply_handler=self.datastore_write_cb,
                            error_handler=self.datastore_write_error_cb)

    def datastore_write_cb(self):
        self._unselect()

    def datastore_write_error_cb(self, error):
        _logger.error('datastore_write_error_cb: %r' % error)

    def _keypress_cb(self, area, event):
        ''' Keyboard '''
        keyname = Gdk.keyval_name(event.keyval)
        keyunicode = Gdk.keyval_to_unicode(event.keyval)
        if event.get_state() & Gdk.ModifierType.MOD1_MASK:
            alt_mask = True
        else:
            alt_mask = False
        self._key_press(alt_mask, keyname, keyunicode)
        return keyname

    def _key_press(self, alt_mask, keyname, keyunicode):
        if keyname is None:
            return False
        self._keypress = keyname
        if alt_mask:
            if keyname == 'q':
                exit()
        elif not self._thumbnail_mode:
            if keyname == 'Home':
                self._first_cb()
            elif keyname == 'Left':
                self._prev_cb()
            elif keyname == 'Right' or keyname == 'space':
                self._next_cb()
            elif keyname == 'End':
                self._last_cb()
        return True

    def _unselect(self):
        if hasattr(self, 'text_entry'):
            if self._selected_spr is not None:
                if self._selected_spr.type == 'comment':
                    if self._tablet_mode:
                        self._OSK_shift(self._selected_spr, OSK_SHIFT)
            self.text_entry.hide()

        if self._selected_spr is not None:
            slide = self._slides[self.i]
            if self._selected_spr.type == 'title':
                slide.title = self._selected_spr.labels[0]
                if self.initiating is not None and self.initiating:
                    self._send_event('t', {"data": (self._data_dumper(
                        [slide.uid, slide.title]))})
                slide.dirty = True
            elif self._selected_spr.type == 'description':
                slide.description = self._selected_spr.labels[0]
                if self.initiating is not None:
                    self._send_event('d', {"data": (
                        self._data_dumper([slide.uid, slide.description]))})
                slide.dirty = True
            elif self._selected_spr.type == 'comment':
                message = self._selected_spr.labels[0]
                if message != '':
                    slide.comment.append({'from': profile.get_nick_name(),
                                          'message': message,
                                          # Use my colors in case of sharing
                                          'icon-color': '[%s,%s]' % (
                        self._my_colors[0], self._my_colors[1])})
                    if self.initiating is not None:
                        self._send_event('c', {"data": (self._data_dumper(
                            [slide.uid, slide.comment]))})
                    self._comment.set_label(parse_comments(slide.comment))
                    self._selected_spr.set_label('')
                    slide.dirty = True
        self._selected_spr = None
        self._saved_string = ''

    def _restore_cursor(self):
        ''' No longer waiting, so restore standard cursor. '''
        if not hasattr(self, 'get_window'):
            return
        self.get_window().set_cursor(self.old_cursor)

    def _waiting_cursor(self):
        ''' Waiting, so set watch cursor. '''
        if not hasattr(self, 'get_window'):
            return
        self.old_cursor = self.get_window().get_cursor()
        self.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.WATCH))

    # Serialize

    def _dump(self, slide):
        ''' Dump data for sharing.'''
        _logger.debug('dumping %s' % (slide.uid))
        if slide.preview is None:
            data = [slide.uid, slide.title, None, slide.description,
                    slide.comment]
        else:
            data = [slide.uid, slide.title,
                    pixbuf_to_base64(activity, slide.preview,
                                     width=300, height=225),
                    slide.description, slide.comment]
        return self._data_dumper(data)

    def _data_dumper(self, data):
        return json.dumps(data)

    def _load(self, data):
        ''' Load slide data from a sharer. '''
        self._restore_cursor()
        uid, title, base64, description, comment = self._data_loader(data)
        if self._uid_to_slide(uid) is None:
            _logger.debug('loading %s' % (uid))
            if base64 is None:
                preview = None
            else:
                preview = base64_to_pixbuf(activity, base64)
            self._slides.append(Slide(self._buddies[-1],
                                      uid,
                                      self._colors,
                                      title,
                                      preview,
                                      description,
                                      comment))
        else:
            _logger.debug('updating description for %s' % (uid))
            slide = self._uid_to_slide(uid)
            slide.title = title
            if base64 is None:
                slide.preview = None
            else:
                slide.preview = base64_to_pixbuf(activity, base64)
            slide.description = description
            slide.comment = comment
            slide.active = True
            if not slide.fav:
                slide.fav = True
                if slide.star is not None:
                    slide.star.set_shape(self._fav_pixbuf)
                    slide.star.type = 'star'

        self._nobjects += 1

        if not self._thumbnail_mode:
            self._thumb_button.set_active(True)
        else:
            self._show_thumbs()

    def _data_loader(self, data):
        return json.loads(data)

    # When portfolio is shared, only sharer sends out slides, joiners
    # send back comments.

    def _setup_presence_service(self):
        ''' Setup the Presence Service. '''
        self.pservice = presenceservice.get_instance()

        owner = self.pservice.get_owner()
        self.owner = owner
        self.buddies = [owner]
        self._share = ''
        self.connect('shared', self._shared_cb)
        self.connect('joined', self._joined_cb)

    def _shared_cb(self, activity):
        ''' Either set up initial share...'''
        if self.get_shared_activity() is None:
            _logger.error('Failed to share or join activity ... \
                shared_activity is null in _shared_cb()')
            return

        self.initiating = True
        self.waiting = False
        _logger.debug('I am sharing...')

        self.conn = self.shared_activity.telepathy_conn
        self.tubes_chan = self.shared_activity.telepathy_tubes_chan
        self.text_chan = self.shared_activity.telepathy_text_chan

        self.tubes_chan[TelepathyGLib.IFACE_CHANNEL_TYPE_TUBES].connect_to_signal(
            'NewTube', self._new_tube_cb)

        _logger.debug('This is my activity: making a tube...')
        self.tubes_chan[TelepathyGLib.IFACE_CHANNEL_TYPE_TUBES].OfferDBusTube(
            SERVICE, {})

    def _joined_cb(self, activity):
        ''' ...or join an exisiting share. '''
        if self.get_shared_activity() is None:
            _logger.error('Failed to share or join activity ... \
                shared_activity is null in _shared_cb()')
            return

        self.initiating = False
        _logger.debug('I joined a shared activity.')

        self.conn = self.shared_activity.telepathy_conn
        self.tubes_chan = self.shared_activity.telepathy_tubes_chan
        self.text_chan = self.shared_activity.telepathy_text_chan

        self.tubes_chan[TelepathyGLib.IFACE_CHANNEL_TYPE_TUBES].connect_to_signal(
            'NewTube', self._new_tube_cb)

        _logger.debug('I am joining an activity: waiting for a tube...')
        self.tubes_chan[TelepathyGLib.IFACE_CHANNEL_TYPE_TUBES].ListTubes(
            reply_handler=self._list_tubes_reply_cb,
            error_handler=self._list_tubes_error_cb)

        self.waiting = True
        # Since we are joining, clear out the slide list
        for slide in self._slides:
            slide.active = False
        self._clear_screen()
        self.i = 0
        self._current_slide = 0
        self._nobjects = 0
        self._help.hide()
        self._description.set_layer(TOP)
        self._description.set_label(_('Please wait.'))
        self._waiting_cursor()

    def _list_tubes_reply_cb(self, tubes):
        ''' Reply to a list request. '''
        for tube_info in tubes:
            self._new_tube_cb(*tube_info)

    def _list_tubes_error_cb(self, e):
        ''' Log errors. '''
        _logger.error('ListTubes() failed: %s', e)

    def _new_tube_cb(self, id, initiator, type, service, params, state):
        ''' Create a new tube. '''
        _logger.debug('New tube: ID=%d initator=%d type=%d service=%s '
                      'params=%r state=%d', id, initiator, type, service,
                      params, state)

        if (type == TelepathyGLib.IFACE_CHANNEL_TYPE_DBUS_TUBES and service == SERVICE):
            if state == TelepathyGLib.TubeState.LOCAL_PENDING:
                self.tubes_chan[
                    TelepathyGLib.IFACE_CHANNEL_TYPE_TUBES].AcceptDBusTube(id)

            self.collab = CollabWrapper(self)
            self.collab.message.connect(self.event_received_cb)
            self.collab.setup()

            if self.waiting:
                self._share_nick()

    def event_received_cb(self, collab, buddy, msg):
        ''' Data is passed as tuples: cmd:text '''
        command = msg.get("command")
        payload = msg.get("payload")
        dispatch_table = {'s': self._load,
                          'C': self._update_colors,
                          'd': self._update_description,
                          'c': self._update_comment,
                          't': self._update_title,
                          'S': self._update_star,
                          'R': self._reset,
                          'j': self._new_join,
                          }
        _logger.debug('<<< %s' % command)
        dispatch_table[command](payload)

    def _reset(self, data):
        for slide in self._slides:
            slide.active = False

    def _new_join(self, data):
        if data not in self._buddies:
            self._buddies.append(data)
        if self.initiating:
            self._share_nick()
            self._share_colors()
            self._share_slides()

    def _update_star(self, data):
        uid, status = self._data_loader(data)
        slide = self._uid_to_slide(uid)
        if slide is None:
            _logger.debug('slide %s not found' % (uid))
            return
        slide.fav = status
        if slide.star is not None:
            if status:
                slide.star.set_shape(self._fav_pixbuf)
                slide.star.type = 'star'
            else:
                slide.star.set_shape(self._unfav_pixbuf)
                slide.star.type = 'unstar'

    def _update_colors(self, data):
        colors = self._data_loader(data)
        colors[0] = str(colors[0])
        colors[1] = str(colors[1])
        self._my_canvas.set_image(svg_str_to_pixbuf(
            genblank(self._width, self._height, [colors[0], colors[0]])))
        self._title.set_image(
            svg_str_to_pixbuf(genblank(
                int(self._title_wh[0]), int(self._title_wh[1]), colors)))
        self._description.set_image(
            svg_str_to_pixbuf(genblank(
                int(self._desc_wh[0]), int(self._desc_wh[1]), colors)))
        self._comment.set_image(
            svg_str_to_pixbuf(genblank(
                int(self._comment_wh[0]), int(self._comment_wh[1]),
                colors)))
        # Don't update new_comment colors

    def _update_comment(self, data):
        uid, comment = self._data_loader(data)
        slide = self._uid_to_slide(uid)
        if slide is None:
            _logger.debug('slide %s not found' % (uid))
            return
        _logger.debug('updating comment %s' % (uid))
        slide.comment = comment
        if self.i == self._slides.index(slide):
            self._comment.set_label(parse_comments(slide.comment))
        if self.initiating:
            slide.dirty = True

    def _update_title(self, data):
        uid, text = self._data_loader(data)
        slide = self._uid_to_slide(uid)
        if slide is None:
            _logger.debug('slide %s not found' % (uid))
            return
        _logger.debug('updating title %s' % (uid))
        slide.title = text
        if self.i == self._slides.index(slide):
            self._title.set_label(text)
        if self.initiating:
            slide.dirty = True

    def _update_description(self, data):
        uid, text = self._data_loader(data)
        slide = self._uid_to_slide(uid)
        if slide is None:
            _logger.debug('slide %s not found' % (uid))
            return
        _logger.debug('updating title %s' % (uid))
        slide.description = text
        if self.i == self._slides.index(slide):
            self._description.set_label(text)
        if self.initiating:
            slide.dirty = True

    def _share_nick(self):
        _logger.debug('sharing nick')
        self._send_event('j', {"data": (profile.get_nick_name())})

    def _share_colors(self):
        _logger.debug('sharing colors')
        self._send_event('C', {"data": (self._data_dumper(self._colors))})

    def _share_slides(self):
        for slide in self._slides:
            if slide.active and slide.fav:
                _logger.debug('sharing %s' % (slide.uid))
                GLib.idle_add(self._send_event, 's', {"data": (
                    str(self._dump(slide)))})

    def _send_star(self, uid, status):
        _logger.debug('sharing star for %s (%s)' % (uid, str(status)))
        self._send_event('S', {"data": (self._data_dumper([uid, status]))})

    def _send_event(self, command, data):
        ''' Send event through the tube. '''
        if hasattr(self, 'collab') and self.collab is not None:
            _logger.debug('>>> %s' % command)
            data["command"] = command
            self.collab.post(data)

    def _save_as_odp_cb(self, button=None):
        self._get_image_list()

    def _next_image(self, x, image_list):
        if x < len(self._slides):
            self.i = x
            self._show_slide()
            window = self._canvas.get_window()
            pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0,
                                                Gdk.Screen.width(),
                                                Gdk.Screen.height())

            pixbuf.savev('/tmp/slide_%d.png' % x, 'png', [], [])
            image_list.append('/tmp/slide_%d.png' % x)
            self._next_cb()
            GLib.idle_add(self._next_image, x + 1, image_list)
        else:
            pres = TurtleODP()
            pres.create_presentation('/tmp/Portfolio.odp', 1024, 768)
            for file_path in image_list:
                pres.add_image(file_path)

            pres.save_presentation()
            dsobject = datastore.create()
            dsobject.metadata['title'] = '%s.odp' % (
                self.metadata['title'])
            dsobject.metadata['icon-color'] = \
                profile.get_color().to_string()
            dsobject.metadata['mime_type'] = \
                'application/vnd.oasis.opendocument.presentation'
            dsobject.set_file_path('/tmp/Portfolio.odp')
            datastore.write(dsobject)
            dsobject.destroy()
            os.remove('/tmp/Portfolio.odp')
            self.i = 0
            self._show_slide()

    def _get_image_list(self):
        image_list = []
        tmp_dir = os.listdir("/tmp")

        for x in tmp_dir:
            if x.startswith("slide_"):
                try:
                    os.remove("/tmp/" + x)
                except:
                    pass

        self._next_image(0, image_list)


class ChatTube(ExportedGObject):

    ''' Class for setting up tube for sharing '''

    def __init__(self, tube, is_initiator, stack_received_cb):
        super(ChatTube, self).__init__(tube, PATH)
        self.tube = tube
        self.is_initiator = is_initiator  # Are we sharing or joining activity?
        self.stack_received_cb = stack_received_cb
        self.stack = ''

        self.tube.add_signal_receiver(self.send_stack_cb, 'SendText', IFACE,
                                      path=PATH, sender_keyword='sender')

    def send_stack_cb(self, text, sender=None):
        if sender == self.tube.get_unique_name():
            return
        self.stack = text
        self.stack_received_cb(text)

    @signal(dbus_interface=IFACE, signature='s')
    def SendText(self, text):
        self.stack = text
