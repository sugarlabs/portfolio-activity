# -*- coding: utf-8 -*-
#Copyright (c) 2011, 2012 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA


import gtk
import gobject
import subprocess
import os
import time
import string
from shutil import copyfile

from math import sqrt, ceil

from sugar.activity import activity
from sugar import profile
try:
    from sugar.graphics.toolbarbox import ToolbarBox
    HAVE_TOOLBOX = True
except ImportError:
    HAVE_TOOLBOX = False

if HAVE_TOOLBOX:
    from sugar.activity.widgets import ActivityToolbarButton
    from sugar.activity.widgets import StopButton
    from sugar.graphics.toolbarbox import ToolbarButton

from sugar.datastore import datastore
from sugar.graphics.alert import Alert

from sprites import Sprites, Sprite
from exportpdf import save_pdf
from utils import get_path, lighter_color, svg_str_to_pixbuf, svg_rectangle, \
    play_audio_from_file, get_pixbuf_from_journal, genblank, get_hardware, \
    pixbuf_to_base64, base64_to_pixbuf, get_pixbuf_from_file
    
from toolbar_utils import radio_factory, button_factory, separator_factory, \
    combo_factory, label_factory
from grecord import Grecord

from gettext import gettext as _

import logging
_logger = logging.getLogger("portfolio-activity")

try:
    from sugar.graphics import style
    GRID_CELL_SIZE = style.GRID_CELL_SIZE
except ImportError:
    GRID_CELL_SIZE = 0

try:
    _OLD_SUGAR_SYSTEM = False
    import json
    from json import load as jload
    from json import dump as jdump
except(ImportError, AttributeError):
    try:
        import simplejson as json
        from simplejson import load as jload
        from simplejson import dump as jdump
    except ImportError:
        _OLD_SUGAR_SYSTEM = True
from StringIO import StringIO

import telepathy
from dbus.service import signal
from dbus.gobject_service import ExportedGObject
from sugar.presence import presenceservice
from sugar.presence.tubeconn import TubeConnection


SERVICE = 'org.sugarlabs.PortfolioActivity'
IFACE = SERVICE
PATH = '/org/sugarlabs/PortfolioActivity'

# Size and position of title, preview image, and description
PREVIEWW = 600
PREVIEWH = 450
PREVIEWY = 80
TITLEH = 60
DESCRIPTIONH = 250
DESCRIPTIONX = 50
DESCRIPTIONY = 550

TWO = 0
TEN = 1
THIRTY = 2
SIXTY = 3
UNITS = [_('2 seconds'), _('10 seconds'), _('30 seconds'), _('1 minute')]
UNIT_DICTIONARY = {TWO: (UNITS[TWO], 2),
                   TEN: (UNITS[TEN], 10),
                   THIRTY: (UNITS[THIRTY], 30),
                   SIXTY: (UNITS[SIXTY], 60)}
XO1 = 'xo1'
XO15 = 'xo1.5'
XO175 = 'xo1.75'
UNKNOWN = 'unknown'

# sprite layers
DRAG = 6
STAR = 5
TOP = 4
UNDRAG = 3
MIDDLE = 2
BOTTOM = 1
HIDE = 0

DEAD_KEYS = ['grave', 'acute', 'circumflex', 'tilde', 'diaeresis', 'abovering']
DEAD_DICTS = [{'A': 192, 'E': 200, 'I': 204, 'O': 210, 'U': 217, 'a': 224,
               'e': 232, 'i': 236, 'o': 242, 'u': 249},
              {'A': 193, 'E': 201, 'I': 205, 'O': 211, 'U': 218, 'a': 225,
               'e': 233, 'i': 237, 'o': 243, 'u': 250},
              {'A': 194, 'E': 202, 'I': 206, 'O': 212, 'U': 219, 'a': 226,
               'e': 234, 'i': 238, 'o': 244, 'u': 251},
              {'A': 195, 'O': 211, 'N': 209, 'U': 360, 'a': 227, 'o': 245,
               'n': 241, 'u': 361},
              {'A': 196, 'E': 203, 'I': 207, 'O': 211, 'U': 218, 'a': 228,
               'e': 235, 'i': 239, 'o': 245, 'u': 252},
              {'A': 197, 'a': 229}]
NOISE_KEYS = ['Shift_L', 'Shift_R', 'Control_L', 'Caps_Lock', 'Pause',
              'Alt_L', 'Alt_R', 'KP_Enter', 'ISO_Level3_Shift', 'KP_Divide',
              'Escape', 'Return', 'KP_Page_Up', 'Up', 'Down', 'Menu',
              'Left', 'Right', 'KP_Home', 'KP_End', 'KP_Up', 'Super_L',
              'KP_Down', 'KP_Left', 'KP_Right', 'KP_Page_Down', 'Scroll_Lock',
              'Page_Down', 'Page_Up']
WHITE_SPACE = ['space', 'Tab']

CURSOR = '█'
NEWLINE = '\n'

TITLE = 0
PREVIEW = 1
DESCRIPTION = 2
THUMB = 3
FAV = 4
DIRTY = 5

class PortfolioActivity(activity.Activity):
    ''' Make a slideshow from starred Journal entries. '''

    def __init__(self, handle):
        ''' Initialize the toolbars and the work surface '''
        super(PortfolioActivity, self).__init__(handle)

        self.datapath = get_path(activity, 'instance')
        self._buddies = [profile.get_nick_name()]
        self._colors = profile.get_color().to_string().split(',')
        self.initiating = None  # sharing (True) or joining (False)

        self._width = gtk.gdk.screen_width()
        self._height = gtk.gdk.screen_height()
        self._scale = gtk.gdk.screen_height() / 900.

        if hasattr(self, 'get_window') and \
           hasattr(self.get_window(), 'get_cursor'):
            self.old_cursor = self.get_window().get_cursor()
        else:
            self.old_cursor = None

        self._hw = get_hardware()

        self._setup_toolbars()
        self._setup_canvas()

        self._uids = []
        # self._slides = []  # TODO: replace individual arrays???

        self._dirty = []
        self._titles = []
        self._previews = []
        self._descriptions = []
        self._favs = []
        self._thumbs = []

        self._thumbnail_mode = False
        self._find_starred()
        self._setup_workspace()

        self._recording = False
        self._grecord = None
        self._alert = None

        self._keypress = None
        self._selected_spr = None
        self._dead_key = ''
        self._saved_string = ''

        self._setup_presence_service()

    def _setup_canvas(self):
        ''' Create a canvas '''
        self._canvas = gtk.DrawingArea()
        self._canvas.set_size_request(int(gtk.gdk.screen_width()),
                                      int(gtk.gdk.screen_height()))
        self._canvas.show()
        self.set_canvas(self._canvas)
        self.show_all()

        self._canvas.set_flags(gtk.CAN_FOCUS)
        self._canvas.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self._canvas.add_events(gtk.gdk.POINTER_MOTION_MASK)
        self._canvas.add_events(gtk.gdk.BUTTON_RELEASE_MASK)
        self._canvas.add_events(gtk.gdk.KEY_PRESS_MASK)
        self._canvas.connect("expose-event", self._expose_cb)
        self._canvas.connect("button-press-event", self._button_press_cb)
        self._canvas.connect("button-release-event", self._button_release_cb)
        self._canvas.connect("motion-notify-event", self._mouse_move_cb)
        self._canvas.connect("key-press-event", self._keypress_cb)

        self._canvas.grab_focus()

    def _setup_workspace(self):
        ''' Prepare to render the datastore entries. '''

        # Use the lighter color for the text background
        if lighter_color(self._colors) == 0:
            tmp = self._colors[0]
            self._colors[0] = self._colors[1]
            self._colors[1] = tmp

        if not HAVE_TOOLBOX and self._hw[0:2] == 'xo':
            titlef = 18
            descriptionf = 12
        else:
            titlef = 36
            descriptionf = 24

        # Generate the sprites we'll need...
        self._sprites = Sprites(self._canvas)

        if self._nobjects == 0:
            star_size = 55
        else:
            star_size = int(150. / int(ceil(sqrt(self._nobjects))))
        self._fav_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'favorite-on.svg'), star_size, star_size)
        self._unfav_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'favorite-off.svg'), star_size, star_size)
        self._make_stars()

        self.prev_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'go-previous.svg'), 55, 55)
        self.next_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'go-next.svg'), 55, 55)
        self.prev_off_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'go-previous-inactive.svg'), 55, 55)
        self.next_off_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'go-next-inactive.svg'), 55, 55)

        self._prev = Sprite(self._sprites, 0, int((self._height - 55)/ 2),
                            self.prev_off_pixbuf)
        self._prev.set_layer(DRAG)
        self._prev.type = 'prev'
        self._next = Sprite(self._sprites, self._width - 55,
                            int((self._height - 55)/ 2), self.next_pixbuf)
        self._next.set_layer(DRAG)
        self._next.type = 'next'

        self._help = Sprite(
            self._sprites,
            int((self._width - int(PREVIEWW * self._scale)) / 2),
            int(PREVIEWY * self._scale),
            gtk.gdk.pixbuf_new_from_file_at_size(
                os.path.join(activity.get_bundle_path(), 'help.png'),
                int(PREVIEWW * self._scale), int(PREVIEWH * self._scale)))
        self._help.hide()

        self._title = Sprite(self._sprites, 0, 0, svg_str_to_pixbuf(
                genblank(self._width, int(TITLEH * self._scale),
                          self._colors)))
        self._title.set_label_attributes(int(titlef * self._scale),
                                         rescale=False)
        self._title.type = 'title'
        self._preview = Sprite(self._sprites,
            int((self._width - int(PREVIEWW * self._scale)) / 2),
            int(PREVIEWY * self._scale), svg_str_to_pixbuf(genblank(
                    int(PREVIEWW * self._scale), int(PREVIEWH * self._scale),
                    self._colors)))

        self._description = Sprite(self._sprites,
                                   int(DESCRIPTIONX * self._scale),
                                   int(DESCRIPTIONY * self._scale),
                                   svg_str_to_pixbuf(
                genblank(int(self._width - (2 * DESCRIPTIONX * self._scale)),
                          int(DESCRIPTIONH * self._scale),
                          self._colors)))
        self._description.set_label_attributes(int(descriptionf * self._scale))
        self._description.type = 'description'

        self._my_canvas = Sprite(
            self._sprites, 0, 0, svg_str_to_pixbuf(genblank(
                    self._width, self._height, (self._colors[0],
                                                self._colors[0]))))
        self._my_canvas.set_layer(BOTTOM)

        self._clear_screen()

        self.i = 0
        self._show_slide()

        self._playing = False
        self._rate = 10

    def _setup_toolbars(self):
        ''' Setup the toolbars. '''

        self.max_participants = 2  # sharing

        if HAVE_TOOLBOX:
            toolbox = ToolbarBox()

            # Activity toolbar
            activity_button_toolbar = ActivityToolbarButton(self)

            toolbox.toolbar.insert(activity_button_toolbar, 0)
            activity_button_toolbar.show()

            self.set_toolbar_box(toolbox)
            toolbox.show()
            self.toolbar = toolbox.toolbar

            adjust_toolbar = gtk.Toolbar()
            adjust_toolbar_button = ToolbarButton(
                label=_('Adjust'),
                page=adjust_toolbar,
                icon_name='preferences-system')
            adjust_toolbar.show_all()
            adjust_toolbar_button.show()

            record_toolbar = gtk.Toolbar()
            record_toolbar_button = ToolbarButton(
                label=_('Record a sound'),
                page=record_toolbar,
                icon_name='media-audio')
            record_toolbar.show_all()
            record_toolbar_button.show()
        else:
            # Use pre-0.86 toolbar design
            primary_toolbar = gtk.Toolbar()
            toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(toolbox)
            toolbox.add_toolbar(_('Page'), primary_toolbar)
            adjust_toolbar = gtk.Toolbar()
            toolbox.add_toolbar(_('Adjust'), adjust_toolbar)
            record_toolbar = gtk.Toolbar()
            toolbox.add_toolbar(_('Record'), record_toolbar)
            toolbox.show()
            toolbox.set_current_toolbar(1)
            self.toolbar = primary_toolbar

        if HAVE_TOOLBOX:
            toolbox.toolbar.insert(record_toolbar_button, -1)
            toolbox.toolbar.insert(adjust_toolbar_button, -1)

        button_factory('view-fullscreen', self.toolbar,
                       self.do_fullscreen_cb, tooltip=_('Fullscreen'),
                       accelerator='<Alt>Return')

        self._auto_button = button_factory(
            'media-playback-start', self.toolbar,
            self._autoplay_cb, tooltip=_('Autoplay'))

        label = label_factory(adjust_toolbar, _('Adjust playback speed'))
        label.show()

        separator_factory(adjust_toolbar, False, False)

        self._unit_combo = combo_factory(UNITS, adjust_toolbar,
                                         self._unit_combo_cb,
                                         default=UNITS[TEN],
                                         tooltip=_('Adjust playback speed'))
        self._unit_combo.show()

        separator_factory(adjust_toolbar)

        button_factory('system-restart', adjust_toolbar, self._rescan_cb,
                       tooltip=_('Refresh'))

        separator_factory(self.toolbar)

        self._slide_button = radio_factory('slide-view', self.toolbar,
                                           self._slides_cb, group=None,
                                           tooltip=_('Slide view'))

        self._thumb_button = radio_factory('thumbs-view',
                                           self.toolbar,
                                           self._thumbs_cb,
                                           tooltip=_('Thumbnail view'),
                                           group=self._slide_button)

        label_factory(record_toolbar, _('Record a sound') + ':')
        self._record_button = button_factory(
            'media-record', record_toolbar,
            self._record_cb, tooltip=_('Start recording'))

        separator_factory(record_toolbar)

        self._playback_button = button_factory(
            'media-playback-start-insensitive',  record_toolbar,
            self._playback_recording_cb, tooltip=_('Nothing to play'))

        self._save_recording_button = button_factory(
            'sound-save-insensitive', record_toolbar,
            self._wait_for_transcoding_to_finish, tooltip=_('Nothing to save'))

        if HAVE_TOOLBOX:
            separator_factory(activity_button_toolbar)
            self._save_pdf = button_factory(
                'save-as-pdf', activity_button_toolbar,
                self._save_as_pdf_cb, tooltip=_('Save as PDF'))
        else:
            separator_factory(self.toolbar)
            self._save_pdf = button_factory(
                'save-as-pdf', self.toolbar,
                self._save_as_pdf_cb, tooltip=_('Save as PDF'))

        if HAVE_TOOLBOX:
            separator_factory(toolbox.toolbar, True, False)

            stop_button = StopButton(self)
            stop_button.props.accelerator = '<Ctrl>q'
            toolbox.toolbar.insert(stop_button, -1)
            stop_button.show()

    def _destroy_cb(self, win, event):
        ''' Clean up on the way out. '''
        gtk.main_quit()

    def _make_stars(self):
        ''' Make stars to include with thumbnails '''
        self._favs = []
        self._stars = []
        for i in range(self._nobjects):
            self._favs.append(True)
            self._stars.append(Sprite(self._sprites, 0, 0,
                                          self._fav_pixbuf))
            self._stars[-1].type = 'star'
            self._stars[-1].set_layer(STAR)

    def _find_starred(self):
        ''' Find all the _stars in the Journal. '''
        self._uids = []
        self._dirty = []
        self._titles = []
        self._previews = []
        self._descriptions = []
        self._thumbs = []
        self._favs = []
        self._stars = []
        self.dsobjects, self._nobjects = datastore.find({'keep': '1'})
        _logger.debug('found %d starred items', self._nobjects)
        for dsobj in self.dsobjects:
            self._uids.append(dsobj.object_id)
            self._dirty.append(False)
            self._favs.append(True)
            if hasattr(dsobj, 'metadata'):
                if 'title' in dsobj.metadata:
                    self._titles.append(dsobj.metadata['title'])
                else:
                    self._titles.append('')
                if 'description' in dsobj.metadata:
                    self._descriptions.append(dsobj.metadata['description'])
                else:
                    self._descriptions.append('')
                if 'mime_type' in dsobj.metadata and \
                   dsobj.metadata['mime_type'][0:5] == 'image':
                    self._previews.append(
                        get_pixbuf_from_file(dsobj.file_path,
                                             int(PREVIEWW * self._scale),
                                             int(PREVIEWH * self._scale)))
                elif 'preview' in dsobj.metadata:
                    self._previews.append(
                        get_pixbuf_from_journal(dsobj, 300, 225))
                else:
                    self._previews.append(None)
            else:
                _logger.debug('dsobj has no metadata')

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

    def _rescan_cb(self, button=None):
        ''' Rescan the Journal for changes in starred items. '''
        if self.initiating is not None and not self.initiating:
            return
        self._help.hide()
        for thumbnail in self._thumbs:
            thumbnail[0].hide()
        for star in self._stars:
            star.hide()
        self._thumbs = []
        self._find_starred()
        self._make_stars()
        self.i = 0
        if self.initiating:
            self._share_slides()
        if self._thumbnail_mode:
            self._thumbnail_mode = False
            self._thumbs_cb()
        else:
            self._show_slide()

    def _autoplay_cb(self, button=None):
        ''' The autoplay button has been clicked; step through slides. '''
        if self._playing:
            self._stop_autoplay()
        else:
            if self._thumbnail_mode:
                self._thumbnail_mode = False
                self.i = self._current_slide
            self._playing = True
            self._auto_button.set_icon('media-playback-pause')
            self._loop()

    def _stop_autoplay(self):
        ''' Stop autoplaying. '''
        self._playing = False
        self._auto_button.set_icon('media-playback-start')
        if hasattr(self, '_timeout_id') and self._timeout_id is not None:
            gobject.source_remove(self._timeout_id)

    def _loop(self):
        ''' Show a slide and then call oneself with a timeout. '''
        self.i += 1
        if self.i == self._nobjects:
            self.i = 0
        self._show_slide()
        self._timeout_id = gobject.timeout_add(int(self._rate * 1000),
                                               self._loop)

    def _save_as_pdf_cb(self, button=None):
        ''' Export an PDF version of the slideshow to the Journal. '''
        if self.initiating is not None and not self.initiating:
            return
        _logger.debug('saving to PDF...')
        if 'description' in self.metadata:
            tmp_file = save_pdf(self, profile.get_nick_name(),
                                description=self.metadata['description'])
        else:
            tmp_file = save_pdf(self, profile.get_nick_name())

        dsobject = datastore.create()
        dsobject.metadata['title'] = profile.get_nick_name() + ' ' + \
                                     _('Portfolio')
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        dsobject.metadata['mime_type'] = 'application/pdf'
        dsobject.set_file_path(tmp_file)
        dsobject.metadata['activity'] = 'org.laptop.sugar.ReadActivity'
        datastore.write(dsobject)
        dsobject.destroy()
        return

    def _clear_screen(self):
        ''' Clear the screen to the darker of the two XO colors. '''
        self._title.hide()
        self._preview.hide()
        self._description.hide()
        if hasattr(self, '_thumbs'):
            for thumbnail in self._thumbs:
                thumbnail[0].hide()
        for stars in self._stars:
            stars.hide()
        self.invalt(0, 0, self._width, self._height)

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
            return

        # Skip slide if unstarred
        if self.initiating is None or self.initiating and \
           not self._favs[self.i]:
            counter = 0
            while not self._favs[self.i]:
                self.i += direction
                if self.i < 0:
                    self.i = self._nobjects - 1
                elif self.i > self._nobjects - 1:
                    self.i = 0
                counter += 1
                if counter == self._nobjects:
                    _logger.debug('No _stars: nothing to show')
                    return

        if self.i == 0:            
            self._prev.set_image(self.prev_off_pixbuf)
        else:
            self._prev.set_image(self.prev_pixbuf)
        if self.i == self._nobjects - 1:
            self._next.set_image(self.next_off_pixbuf)
        else:
            self._next.set_image(self.next_pixbuf)

        pixbuf = self._previews[self.i]

        if pixbuf is not None:
            self._preview.set_shape(pixbuf.scale_simple(
                    int(PREVIEWW * self._scale),
                    int(PREVIEWH * self._scale),
                    gtk.gdk.INTERP_NEAREST))
            self._preview.set_layer(MIDDLE)
        else:
            if self._preview is not None:
                self._preview.hide()

        # self._title.set_label(self.dsobjects[self.i].metadata['title'])
        self._title.set_label(self._titles[self.i])
        self._title.set_layer(MIDDLE)

        self._description.set_label(self._descriptions[self.i])
        self._description.set_layer(MIDDLE)

        audio_obj = self._search_for_audio_note(
            self.dsobjects[self.i].object_id)
        if audio_obj is not None:
            _logger.debug('Playing audio note')
            gobject.idle_add(play_audio_from_file, audio_obj.file_path)
            self._playback_button.set_icon('media-playback-start')
            self._playback_button.set_tooltip(_('Play recording'))
        else:
            self._playback_button.set_icon('media-playback-start-insensitive')
            self._playback_button.set_tooltip(_('Nothing to play'))

    def _slides_cb(self, button=None):
        if self._thumbnail_mode:
            self._thumbnail_mode = False
            self.i = self._current_slide
            self._show_slide()

    def _thumbs_cb(self, button=None):
        ''' Toggle between thumbnail view and slideshow view. '''
        if not self._thumbnail_mode:
            self._show_thumbs()
        else:
            self._prev.set_layer(DRAG)
            self._next.set_layer(DRAG)
        return False

    def _show_thumbs(self):
        self._stop_autoplay()
        self._current_slide = self.i
        self._thumbnail_mode = True
        self._clear_screen()

        self._prev.hide()
        self._next.hide()

        n = int(ceil(sqrt(self._nobjects)))
        if n > 0:
            w = int(self._width / n)
        else:
            w = self._width
        h = int(w * 0.75)  # maintain 4:3 aspect ratio
        x_off = int((self._width - n * w) / 2)
        x = x_off
        y = 0
        for i in range(self._nobjects):
            self.i = i
            self._show_thumb(x, y, w, h)
            if self.initiating is None or self.initiating:
                self._stars[i].set_layer(STAR)
                self._stars[i].move((x, y))
            x += w
            if x + w > self._width:
                x = x_off
                y += h
        self.i = 0  # Reset position in slideshow to the beginning

    def _show_thumb(self, x, y, w, h):
        ''' Display a preview image and title as a thumbnail. '''

        if len(self._thumbs) < self.i + 1:
            # Create a Sprite for this thumbnail
            if self._previews[self.i] is not None:
                pixbuf_thumb = self._previews[self.i].scale_simple(
                    int(w), int(h), gtk.gdk.INTERP_TILES)
            else:
                pixbuf_thumb = svg_str_to_pixbuf(genblank(int(w), int(h),
                                                          self._colors))
            self._thumbs.append([Sprite(self._sprites, x, y, pixbuf_thumb),
                                     x, y, self.i])
            self._thumbs[-1][0].set_image(svg_str_to_pixbuf(
                    svg_rectangle(int(w), int(h), self._colors)), i=1)
            self._thumbs[-1][0].set_label(str(self.i + 1))
        self._thumbs[self.i][0].set_layer(TOP)

    def _expose_cb(self, win, event):
        ''' Callback to handle window expose events '''
        self.do_expose_event(event)
        return True

    # Handle the expose-event by drawing
    def do_expose_event(self, event):

        # Create the cairo context
        cr = self.canvas.window.cairo_create()

        # Restrict Cairo to the exposed area; avoid extra work
        cr.rectangle(event.area.x, event.area.y,
                event.area.width, event.area.height)
        cr.clip()

        # Refresh sprite list
        self._sprites.redraw_sprites(cr=cr)

    def write_file(self, file_path):
        ''' Clean up '''
        if self.initiating is not None and not self.initiating:
            _logger.debug('I am a joiner, so I am not saving.')
            return

        if True in self._dirty:
            self._save_changes_cb()
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            os.remove(os.path.join(self.datapath, 'output.ogg'))

    def do_fullscreen_cb(self, button):
        ''' Hide the Sugar toolbars. '''
        self.fullscreen()

    def invalt(self, x, y, w, h):
        ''' Mark a region for refresh '''
        self._canvas.window.invalidate_rect(
            gtk.gdk.Rectangle(int(x), int(y), int(w), int(h)), False)

    def _spr_to_thumb(self, spr):
        ''' Find which entry in the thumbnails table matches spr. '''
        for i, thumb in enumerate(self._thumbs):
            if spr == thumb[0]:
                return i
        return -1

    def _spr_is_thumbnail(self, spr):
        ''' Does spr match an entry in the thumbnails table? '''
        if self._spr_to_thumb(spr) == -1:
            return False
        else:
            return True

    def _button_press_cb(self, win, event):
        ''' The mouse button was pressed. Is it on a thumbnail sprite? '''
        x, y = map(int, event.get_coords())

        self._dragpos = [x, y]
        self._total_drag = [0, 0]

        spr = self._sprites.find_sprite((x, y))
        self._press = None
        self._release = None

        # Are we clicking on a title or description?
        if spr.type == 'title' or spr.type == 'description':
            if spr == self._selected_spr:
                return True
            elif self._selected_spr is not None:
                self._unselect()
            self._selected_spr = spr
            self._saved_string = spr.labels[0]
            if spr.type == 'description':
                if self.initiating is not None and not self.initiating:
                    label = '%s\n[%s] %s' % (self._selected_spr.labels[0],
                                             profile.get_nick_name(), CURSOR)
                else:
                    label = '%s%s' % (self._selected_spr.labels[0], CURSOR)
                self._selected_spr.set_label(label)
            elif spr.type == 'title':
                if self.initiating is None or self.initiating:
                    label = '%s%s' % (self._selected_spr.labels[0], CURSOR)
                    self._selected_spr.set_label(label)
                else:
                    self._selected_spr = None
        else:
            self._unselect()

        # Are we clicking on a button?
        if spr.type == 'next':
            self._next_cb()
            return True
        elif spr.type == 'prev':
            self._prev_cb()
            return True

        # Are we clicking on a star?
        if spr.type == 'star':
            spr.set_shape(self._unfav_pixbuf)
            spr.type = 'unstar'
            i = self._stars.index(spr)
            self._favs[i] = False
            if self.initiating:
                self.send_star(i, False)
        elif spr.type == 'unstar':
            spr.set_shape(self._fav_pixbuf)
            spr.type = 'star'
            i = self._stars.index(spr)
            self._favs[i] = True
            if self.initiating:
                self.send_star(i, True)

        # Are we clicking on a thumbnail?
        if not self._spr_is_thumbnail(spr):
            return False

        self.last_spr_moved = spr
        self._press = spr
        self._press.set_layer(DRAG)
        if self.initiating is None or self.initiating:
            self._stars[self._spr_to_thumb(self._press)].set_layer(DRAG+1)
        return False

    def _mouse_move_cb(self, win, event):
        """ Drag a thumbnail with the mouse. """
        spr = self._press
        if spr is None:
            self._dragpos = [0, 0]
            return False
        win.grab_focus()
        x, y = map(int, event.get_coords())
        dx = x - self._dragpos[0]
        dy = y - self._dragpos[1]
        spr.move_relative([dx, dy])
        # Also move the star
        if self.initiating is None or self.initiating:
            self._stars[self._spr_to_thumb(spr)].move_relative([dx, dy])
        self._dragpos = [x, y]
        self._total_drag[0] += dx
        self._total_drag[1] += dy
        return False

    def _button_release_cb(self, win, event):
        ''' Button event is used to swap slides or goto next slide. '''
        win.grab_focus()
        self._dragpos = [0, 0]
        x, y = map(int, event.get_coords())

        if self._press is None:
            return

        if self._thumbnail_mode:
            i = self._spr_to_thumb(self._press)
            # Drop the dragged thumbnail below the other thumbnails so
            # that you can find the thumbnail beneath it...
            self._press.set_layer(UNDRAG)
            if self.initiating is None or self.initiating:
                self._stars[self._spr_to_thumb(self._press)].set_layer(STAR)
            spr = self._sprites.find_sprite((x, y))
            self._press.set_layer(TOP)  # and then restore press to top layer

            if self._spr_is_thumbnail(spr):
                self._release = spr
                # If we found a thumbnail
                # ...and it is the one we dragged, jump to that slide.
                if self._press == self._release:
                    if self._total_drag[0] * self._total_drag[0] + \
                       self._total_drag[1] * self._total_drag[1] < 200:
                        self._current_slide = self._spr_to_thumb(self._release)
                        self._slide_button.set_active(True)
                # ...and it is not the one we dragged, swap their positions.
                else:
                    j = self._spr_to_thumb(self._release)
                    self._thumbs[i][0] = self._release
                    self._thumbs[j][0] = self._press
                    tmp = self.dsobjects[i]
                    self.dsobjects[i] = self.dsobjects[j]
                    self.dsobjects[j] = tmp
                    if self.initiating is None or self.initiating:
                        tmp = self._stars[i]
                        self._stars[i] = self._stars[j]
                        self._stars[j] = tmp
                    tmp = self._uids[i]
                    self._uids[i] = self._uids[j]
                    self._uids[j] = tmp
                    tmp = self._titles[i]
                    self._titles[i] = self._titles[j]
                    self._titles[j] = tmp
                    tmp = self._previews[i]
                    self._previews[i] = self._previews[j]
                    self._previews[j] = tmp
                    tmp = self._descriptions[i]
                    self._descriptions[i] = self._descriptions[j]
                    self._descriptions[j] = tmp
                    self._thumbs[j][0].move((self._thumbs[j][1],
                                             self._thumbs[j][2]))
                    if self.initiating is None or self.initiating:
                        self._stars[j].move((self._thumbs[j][1],
                                                 self._thumbs[j][2]))
            self._thumbs[i][0].move((self._thumbs[i][1], self._thumbs[i][2]))
            if self.initiating is None or self.initiating:
                self._stars[i].move((self._thumbs[i][1],
                                         self._thumbs[i][2]))
        self._press = None
        self._release = None
        return False

    def _unit_combo_cb(self, arg=None):
        ''' Read value of predefined conversion factors from combo box '''
        if hasattr(self, '_unit_combo'):
            active = self._unit_combo.get_active()
            if active in UNIT_DICTIONARY:
                self._rate = UNIT_DICTIONARY[active][1]

    def _record_cb(self, button=None):
        ''' Start/stop audio recording '''
        if self.initiating is not None and not self.initiating:
            return
        if self._grecord is None:
            _logger.debug('setting up grecord')
            self._grecord = Grecord(self)
        if self._recording:  # Was recording, so stop (and save?)
            _logger.debug('recording...True. Preparing to save.')
            self._grecord.stop_recording_audio()
            self._recording = False
            self._record_button.set_icon('media-record')
            self._record_button.set_tooltip(_('Start recording'))
            self._playback_button.set_icon('media-playback-start')
            self._playback_button.set_tooltip(_('Play recording'))
            self._save_recording_button.set_icon('sound-save')
            self._save_recording_button.set_tooltip(_('Save recording'))
            # Autosave if there was not already a recording
            if self._search_for_audio_note(
                self.dsobjects[self.i].object_id) is None:
                _logger.debug('Autosaving recording')
                self._notify_successful_save(title=_('Save recording'))
                gobject.timeout_add(100, self._wait_for_transcoding_to_finish)
            else:
                _logger.debug('Waiting for manual save.')
        else:  # Wasn't recording, so start
            _logger.debug('recording...False. Start recording.')
            self._grecord.record_audio()
            self._recording = True
            self._record_button.set_icon('media-recording')
            self._record_button.set_tooltip(_('Stop recording'))

    def _wait_for_transcoding_to_finish(self, button=None):
        while not self._grecord.transcoding_complete():
            time.sleep(1)
        if self._alert is not None:
            self.remove_alert(self._alert)
            self._alert = None
        self._save_recording()

    def _playback_recording_cb(self, button=None):
        ''' Play back current recording '''
        _logger.debug('Playback current recording from output.ogg...')
        play_audio_from_file(os.path.join(self.datapath, 'output.ogg'))
        return

    def _save_recording(self):
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            _logger.debug('Saving recording to Journal...')
            obj_id = self.dsobjects[self.i].object_id
            copyfile(os.path.join(self.datapath, 'output.ogg'),
                     os.path.join(self.datapath, '%s.ogg' % (obj_id)))
            dsobject = self._search_for_audio_note(obj_id)
            if dsobject is None:
                dsobject = datastore.create()
            if dsobject is not None:
                _logger.debug(self.dsobjects[self.i].metadata['title'])
                dsobject.metadata['title'] = _('audio note for %s') % \
                    (self.dsobjects[self.i].metadata['title'])
                dsobject.metadata['icon-color'] = \
                    profile.get_color().to_string()
                dsobject.metadata['tags'] = obj_id
                dsobject.metadata['mime_type'] = 'audio/ogg'
                dsobject.set_file_path(
                    os.path.join(self.datapath, '%s.ogg' % (obj_id)))
                    # os.path.join(self.datapath, 'output.ogg'))
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
        for i, uid in enumerate(self._uids):
            if not self._dirty[i]:
                _logger.debug('%d is not dirty...' % (i))
                continue
            _logger.debug('%d is dirty... writing' % (i))
            jobject = datastore.get(uid)
            jobject.metadata['description'] = self._descriptions[i]
            jobject.metadata['title'] = self._titles[i]
            datastore.write(jobject,
                            update_mtime=False,
                            reply_handler=self.datastore_write_cb,
                            error_handler=self.datastore_write_error_cb)

    def datastore_write_cb(self):
        pass

    def datastore_write_error_cb(self, error):
        _logger.error('datastore_write_error_cb: %r' % error)

    def _notify_successful_save(self, title='', msg=''):
        ''' Notify user when saves are completed '''
        self._alert = Alert()
        self._alert.props.title = title
        self._alert.props.msg = msg
        self.add_alert(self._alert)
        self._alert.show()

    def _keypress_cb(self, area, event):
        ''' Keyboard '''
        keyname = gtk.gdk.keyval_name(event.keyval)
        keyunicode = gtk.gdk.keyval_to_unicode(event.keyval)
        if event.get_state() & gtk.gdk.MOD1_MASK:
            alt_mask = True
            alt_flag = 'T'
        else:
            alt_mask = False
            alt_flag = 'F'
        self._key_press(alt_mask, keyname, keyunicode)
        return keyname

    def _key_press(self, alt_mask, keyname, keyunicode):
        if keyname is None:
            return False
        self._keypress = keyname
        if alt_mask:
            if keyname == 'q':
                exit()
        elif self._selected_spr is not None:
            self.process_alphanumeric_input(keyname, keyunicode)
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

    def process_alphanumeric_input(self, keyname, keyunicode):
        ''' Make sure alphanumeric input is properly parsed. '''
        if len(self._selected_spr.labels[0]) > 0:
            c = self._selected_spr.labels[0].count(CURSOR)
            if c == 0:
                oldleft = self._selected_spr.labels[0]
                oldright = ''
            elif len(self._selected_spr.labels[0]) == 1:
                oldleft = ''
                oldright = ''
            elif CURSOR in self._selected_spr.labels[0]:
                oldleft, oldright = \
                    self._selected_spr.labels[0].split(CURSOR)
            else:  # Where did our cursor go?
                oldleft = self._selected_spr.labels[0]
                oldright = ''
        else:
            oldleft = ''
            oldright = ''
        newleft = oldleft
        if keyname in ['Shift_L', 'Shift_R', 'Control_L', 'Caps_Lock', \
                       'Alt_L', 'Alt_R', 'KP_Enter', 'ISO_Level3_Shift']:
            keyname = ''
            keyunicode = 0
        # Hack until I sort out input and unicode and dead keys,
        if keyname[0:5] == 'dead_':
            self._dead_key = keyname
            keyname = ''
            keyunicode = 0
        if keyname == 'space':
            keyunicode = 32
        elif keyname == 'Tab':
            keyunicode = 9
        if keyname == 'BackSpace':
            if len(oldleft) > 1:
                newleft = oldleft[:len(oldleft) - 1]
            else:
                newleft = ''
        if keyname == 'Delete':
            if len(oldright) > 0:
                oldright = oldright[1:]
        elif keyname == 'Home':
            oldright = oldleft + oldright
            newleft = ''
        elif keyname == 'Left':
            if len(oldleft) > 0:
                oldright = oldleft[len(oldleft) - 1:] + oldright
                newleft = oldleft[:len(oldleft) - 1]
        elif keyname == 'Right':
            if len(oldright) > 0:
                newleft = oldleft + oldright[0]
                oldright = oldright[1:]
        elif keyname == 'End':
            newleft = oldleft + oldright
            oldright = ''
        elif keyname == 'Return':
            newleft = oldleft + NEWLINE
        elif keyname == 'Down':
            if NEWLINE in oldright:
                parts = oldright.split(NEWLINE)
                newleft = oldleft + string.join(parts[0:2], NEWLINE)
                oldright = NEWLINE + string.join(parts[2:], NEWLINE)
        elif keyname == 'Up':
            if NEWLINE in oldleft:
                parts = oldleft.split(NEWLINE)
                newleft = string.join(parts[0:-1], NEWLINE)
                oldright = NEWLINE + parts[-1] + oldright
        elif keyname == 'Escape':  # Restore previous state
            self._selected_spr.set_label(self._saved_string)
            self._unselect()
            return
        else:
            if self._dead_key is not '':
                keyunicode = \
                    DEAD_DICTS[DEAD_KEYS.index(self._dead_key[5:])][keyname]
                self._dead_key = ''
            if keyunicode > 0:
                if unichr(keyunicode) != '\x00':
                    newleft = oldleft + unichr(keyunicode)
                else:
                    newleft = oldleft
            elif keyunicode == -1:  # clipboard text
                if keyname == NEWLINE:
                    newleft = oldleft + NEWLINE
                else:
                    newleft = oldleft + keyname
        self._selected_spr.set_label("%s%s%s" % (newleft, CURSOR, oldright))

    def _unselect(self):
        if self._selected_spr is not None:
            if CURSOR in self._selected_spr.labels[0]:
                parts = self._selected_spr.labels[0].split(CURSOR)
                self._selected_spr.set_label(string.join(parts))
                if self._selected_spr.type == 'title':
                    self._titles[self.i] = self._selected_spr.labels[0]
                    if self.initiating is not None and \
                       self.initiating:
                        self._send_event('t:%s' % (self._data_dumper(
                                    [self._uids[self.i],
                                     self._titles[self.i]])))
                else:
                    self._descriptions[self.i] = self._selected_spr.labels[0]
                    if self.initiating is not None:
                        self._send_event('d:%s' % (self._data_dumper(
                                    [self._uids[self.i],
                                     self._descriptions[self.i]])))
                _logger.debug('marking %d as dirty' % (self.i))
                self._dirty[self.i] = True
            self._selected_spr = None
            self._saved_string = ''

    def _restore_cursor(self):
        ''' No longer waiting, so restore standard cursor. '''
        if not hasattr(self, 'get_window'):
            return
        if hasattr(self.get_window(), 'get_cursor'):
            self.get_window().set_cursor(self.old_cursor)
        else:
            self.get_window().set_cursor(gtk.gdk.Cursor(gtk.gdk.LEFT_PTR))

    def _waiting_cursor(self):
        ''' Waiting, so set watch cursor. '''
        if not hasattr(self, 'get_window'):
            return
        if hasattr(self.get_window(), 'get_cursor'):
            self.old_cursor = self.get_window().get_cursor()
        self.get_window().set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

    # Serialize

    def _dump(self, uid, title, pixbuf, description):
        ''' Dump data for sharing.'''
        _logger.debug('dumping %s' % (uid))
        if pixbuf is None:
            data = [uid, title, None, description]
        else:
            data = [uid, title, pixbuf_to_base64(activity, pixbuf), description]
        return self._data_dumper(data)

    def _data_dumper(self, data):
        if _OLD_SUGAR_SYSTEM:
            return json.write(data)
        else:
            io = StringIO()
            jdump(data, io)
            return io.getvalue()

    def _load(self, data):
        ''' Load game data from the journal. '''
        self._restore_cursor()
        uid, title, base64, description = self._data_loader(data)
        if not uid in self._uids:
            _logger.debug('loading %s' % (uid))
            self._uids.append(uid)
            self._titles.append(title)
            if base64 is None:
                self._previews.append(None)
            else:
                self._previews.append(base64_to_pixbuf(activity, base64))
            self._descriptions.append(description)
            self._nobjects += 1
            for thumbnail in self._thumbs:
                thumbnail[0].hide()
            self._thumbs = []
            if not self._thumbnail_mode:
                self._thumb_button.set_active(True)
            else:
                self._show_thumbs()
        else:
            _logger.debug('updating description for %s' % (uid))
            self._titles[self._uids.index(uid)] = title
            if base64 is None:
                self._previews[self._uids.index(uid)] = None
            else:
                self._previews[self._uids.index(uid)] = base64_to_pixbuf(
                    activity, base64)
            self._descriptions[self._uids.index(uid)] = description

    def _data_loader(self, data):
        if _OLD_SUGAR_SYSTEM:
            return json.read(data)
        else:
            io = StringIO(data)
            return jload(io)

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
        if self._shared_activity is None:
            _logger.error('Failed to share or join activity ... \
                _shared_activity is null in _shared_cb()')
            return

        self.initiating = True
        self.waiting = False
        _logger.debug('I am sharing...')

        self.conn = self._shared_activity.telepathy_conn
        self.tubes_chan = self._shared_activity.telepathy_tubes_chan
        self.text_chan = self._shared_activity.telepathy_text_chan

        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(
            'NewTube', self._new_tube_cb)

        _logger.debug('This is my activity: making a tube...')
        id = self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].OfferDBusTube(
            SERVICE, {})

    def _joined_cb(self, activity):
        ''' ...or join an exisiting share. '''
        if self._shared_activity is None:
            _logger.error('Failed to share or join activity ... \
                _shared_activity is null in _shared_cb()')
            return

        self.initiating = False
        _logger.debug('I joined a shared activity.')

        self.conn = self._shared_activity.telepathy_conn
        self.tubes_chan = self._shared_activity.telepathy_tubes_chan
        self.text_chan = self._shared_activity.telepathy_text_chan

        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(\
            'NewTube', self._new_tube_cb)

        _logger.debug('I am joining an activity: waiting for a tube...')
        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].ListTubes(
            reply_handler=self._list_tubes_reply_cb,
            error_handler=self._list_tubes_error_cb)

        self.waiting = True
        # Since we are joining, clear out the slide list
        self._uids = []
        self._dirty = []
        self._titles = []
        self._previews = []
        self._descriptions = []
        self._thumbs = []
        self._nobjects = 0
        self._clear_screen()
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

        if (type == telepathy.TUBE_TYPE_DBUS and service == SERVICE):
            if state == telepathy.TUBE_STATE_LOCAL_PENDING:
                self.tubes_chan[ \
                              telepathy.CHANNEL_TYPE_TUBES].AcceptDBusTube(id)

            tube_conn = TubeConnection(self.conn,
                self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES], id, \
                group_iface=self.text_chan[telepathy.CHANNEL_INTERFACE_GROUP])

            self.chattube = ChatTube(tube_conn, self.initiating, \
                self.event_received_cb)

            if self.waiting:
                self._send_event('j:%s' % (profile.get_nick_name()))

    def event_received_cb(self, text):
        ''' Data is passed as tuples: cmd:text '''
        dispatch_table = {'s': self._load,
                          'c': self._update_colors,
                          'd': self._update_description,
                          't': self._update_title,
                          'S': self._update_star,
                          'j': self._new_join,
                          }
        _logger.debug('<<< %s' % (text[0]))
        dispatch_table[text[0]](text[2:])

    def _new_join(self, data):
        if data not in self._buddies:
            self._buddies.append(data)
        if self.initiating:
            self._share_colors()
            self._share_slides()

    def _update_star(self, data):
        i, status = self._data_loader(data)
        self._favs[i] = status

    def _update_colors(self, data):
        colors = self._data_loader(data)
        if colors[0] != self._colors[0] or \
           colors[1] != self._colors[1]:
            self._colors = colors[:]
            self._my_canvas.set_image(svg_str_to_pixbuf(
                genblank(self._width, self._height, [self._colors[0],
                                                     self._colors[0]])))
            self._description.set_image(svg_str_to_pixbuf(
                    genblank(
                        int(self._width - (2 * DESCRIPTIONX * self._scale)),
                        int(DESCRIPTIONH * self._scale), self._colors)))
            self._title.set_image(svg_str_to_pixbuf(
                        genblank(self._width, int(TITLEH * self._scale),
                                 self._colors)))

    def _update_description(self, data):
        uid, text = self._data_loader(data)
        if uid in self._uids:
            _logger.debug('updating description %s' % (uid))
            self._descriptions[self._uids.index(uid)] = text
            if self.i == self._uids.index(uid):
                self._description.set_label(text)
            if self.initiating:
                self._dirty[self._uids.index(uid)] = True

    def _update_title(self, data):
        uid, text = self._data_loader(data)
        if uid in self._uids:
            _logger.debug('updating title %s' % (uid))
            self._titles[self._uids.index(uid)] = text
            if self.i == self._uids.index(uid):
                self._title.set_label(text)

    def _share_colors(self):
        _logger.debug('sharing colors')
        self._send_event('c:%s' % (self._data_dumper(self._colors)))

    def _share_slides(self):
        for i in range(len(self._uids)):
            if self._favs[i]:
                _logger.debug('sharing %s' % (self._uids[i]))
                gobject.idle_add(self._send_event, 's:' + str(
                        self._dump(self._uids[i],
                                   self._titles[i],
                                   self._previews[i],
                                   self._descriptions[i])))

    def _send_star(self, i, status):
        _logger.debug('sharing star for %s (%s)' % (self._uids[i], str(status)))
        self._send_event('S:%s' % (self._dump(self._uids[i], status)))

    def _send_event(self, text):
        ''' Send event through the tube. '''
        if hasattr(self, 'chattube') and self.chattube is not None:
            _logger.debug('>>> %s' % (text[0]))
            self.chattube.SendText(text)


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
