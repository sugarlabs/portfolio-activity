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


class Slide():
    ''' A container for a slide '''

    def __init__(self, owner, uid, colors, title, preview, desc):
        self.active = True
        self.owner = owner
        self.uid = uid
        self.colors = colors
        self.title = title
        self.preview = preview
        self.preview2 = None  # larger version for fullscreen mode
        self.description = desc
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
        self.initiating = None  # sharing (True) or joining (False)

        self._playing = False
        self._first_time = True

        self._width = gtk.gdk.screen_width()
        self._height = gtk.gdk.screen_height()
        self._scale = gtk.gdk.screen_height() / 900.

        self._titlewh = [self._width, TITLEH * self._scale]
        self._titlexy = [0, 0]
        self._previewwh = [PREVIEWW * self._scale, PREVIEWH * self._scale]
        self._previewxy = [(self._width - self._previewwh[0]) / 2,
                           PREVIEWY * self._scale]
        self._descriptionwh = [self._width,
                               self._height - DESCRIPTIONY * self._scale - 55]
        self._descriptionxy = [0, DESCRIPTIONY * self._scale]

        if hasattr(self, 'get_window') and \
           hasattr(self.get_window(), 'get_cursor'):
            self.old_cursor = self.get_window().get_cursor()
        else:
            self.old_cursor = None

        self._hw = get_hardware()

        self._setup_toolbars()
        self._setup_canvas()

        self._slides = []
        self._current_slide = 0

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
        self._startpos = [0, 0]
        self._dragpos = [0, 0]

        self._setup_presence_service()

    def _tablet_mode(self):
        return True

    def _fixed_resize_cb(self, widget=None, rect=None):
        ''' If a toolbar opens or closes, we need to resize the vbox
        holding out scrolling window. '''
        self.vbox.set_size_request(rect[2], rect[3])

    def _setup_canvas(self):
        ''' Create a canvas inside a gtk.Fixed '''

        self.fixed = gtk.Fixed()
        self.fixed.connect('size-allocate', self._fixed_resize_cb)
        self.fixed.show()
        self.set_canvas(self.fixed)

        self.vbox = gtk.VBox(False, 0)
        self.vbox.set_size_request(
            gtk.gdk.screen_width(),
            gtk.gdk.screen_height() - style.GRID_CELL_SIZE)
        self.fixed.put(self.vbox, 0, 0)
        self.vbox.show()

        self._canvas = gtk.DrawingArea()
        self._canvas.set_size_request(int(gtk.gdk.screen_width()),
                                      int(gtk.gdk.screen_height()))
        self._canvas.show()
        # self.set_canvas(self._canvas)
        self.show_all()
        self.vbox.pack_end(self._canvas, True, True)
        self.vbox.show()

        self._canvas.set_flags(gtk.CAN_FOCUS)
        self._canvas.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self._canvas.add_events(gtk.gdk.POINTER_MOTION_MASK)
        self._canvas.add_events(gtk.gdk.BUTTON_RELEASE_MASK)
        self._canvas.add_events(gtk.gdk.KEY_PRESS_MASK)
        self._canvas.add_events(gtk.gdk.CONFIGURE)
        self._canvas.connect('expose-event', self._expose_cb)
        self._canvas.connect('button-press-event', self._button_press_cb)
        self._canvas.connect('button-release-event', self._button_release_cb)
        self._canvas.connect('motion-notify-event', self._mouse_move_cb)
        self._canvas.connect('key-press-event', self._keypress_cb)
        self._canvas.connect('configure-event', self._configure_cb)

        self._canvas.grab_focus()

    def _configure_cb(self, win, event):
        # landscape or portrait?
        self._width = gtk.gdk.screen_width()
        self._height = gtk.gdk.screen_height()
        if self._width > self._height:
            self._scale = gtk.gdk.screen_height() / 900.
        else:
            self._scale = gtk.gdk.screen_width() / 1200.

        self._my_canvas.hide()
        self._title.hide()
        self._description.hide()
        self._titlewh = [self._width, TITLEH * self._scale]
        self._titlexy = [0, 0]
        self._previewwh = [PREVIEWW * self._scale, PREVIEWH * self._scale]
        self._previewxy = [(self._width - self._previewwh[0]) / 2,
                           PREVIEWY * self._scale]
        self._descriptionwh = [self._width,
                               self._height - DESCRIPTIONY * self._scale - 55]
        self._descriptionxy = [0, DESCRIPTIONY * self._scale]

        self._configured_sprites()  # Some sprites are sized to screen
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

        if not HAVE_TOOLBOX and self._hw[0:2] == 'xo':
            self._titlef = 18
            self._descriptionf = 12
        else:
            self._titlef = 36
            self._descriptionf = 24

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

        self.record_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'media-audio.svg'), 55, 55)
        self.recording_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'media-audio-recording.svg'), 55, 55)
        self.playback_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'speaker-100.svg'), 55, 55)
        self.playing_pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
            os.path.join(activity.get_bundle_path(), 'icons',
                         'speaker-0.svg'), 55, 55)

        self._record_button = Sprite(self._sprites, 0, 0, self.record_pixbuf)
        self._record_button.set_layer(DRAG)
        self._record_button.type = 'record'

        self._playback_button = Sprite(self._sprites, 0, 0,
                                       self.playback_pixbuf)
        self._playback_button.type = 'noplay'
        self._playback_button.hide()

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

        self._prev = Sprite(self._sprites, 0, 0, self.prev_off_pixbuf)
        self._prev.set_layer(DRAG)
        self._prev.type = 'prev'

        self._next = Sprite(self._sprites, 0, 0, self.next_pixbuf)
        self._next.set_layer(DRAG)
        self._next.type = 'next'

        self._help = Sprite(self._sprites,
                            0, 0,
                            gtk.gdk.pixbuf_new_from_file_at_size(
                os.path.join(activity.get_bundle_path(), 'help.png'),
                int(self._previewwh[0]),
                int(self._previewwh[1])))
        self._help.hide()

        self._preview = Sprite(self._sprites,
                               0, 0,
                               svg_str_to_pixbuf(genblank(
                        int(self._previewwh[0]),
                        int(self._previewwh[1]),
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

        self._preview.move((int(self._previewxy[0]),
                            int(self._previewxy[1])))
        self._help.move((int(self._previewxy[0]),
                         int(self._previewxy[1])))
        self._record_button.move((self._width - 55, self._titlewh[1]))
        self._playback_button.move((self._width - 55, self._titlewh[1] + 55))
        self._prev.move((0, int((self._height - 55) / 2)))
        self._next.move((self._width - 55, int((self._height - 55) / 2)))
        self._title = Sprite(self._sprites,
                             int(self._titlexy[0]),
                             int(self._titlexy[1]),
                             svg_str_to_pixbuf(
                genblank(self._titlewh[0], self._titlewh[1], self._colors)))
        self._title.set_label_attributes(int(self._titlef * self._scale),
                                         rescale=False)
        self._title.type = 'title'

        self._description = Sprite(self._sprites,
                                   int(self._descriptionxy[0]),
                                   int(self._descriptionxy[1]),
                                   svg_str_to_pixbuf(
                genblank(int(self._descriptionwh[0]),
                         int(self._descriptionwh[1]),
                         self._colors)))
        self._description.set_label_attributes(
            int(self._descriptionf * self._scale))
        self._description.type = 'description'

        self._my_canvas = Sprite(
            self._sprites, 0, 0, svg_str_to_pixbuf(genblank(
                    self._width, self._height, (self._colors[0],
                                                self._colors[0]))))
        self._my_canvas.set_layer(BOTTOM)
        self._my_canvas.type = 'background'

    def _setup_toolbars(self):
        ''' Setup the toolbars. '''

        self.max_participants = 5  # sharing

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
        else:
            # Use pre-0.86 toolbar design
            primary_toolbar = gtk.Toolbar()
            toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(toolbox)
            toolbox.add_toolbar(_('Page'), primary_toolbar)
            adjust_toolbar = gtk.Toolbar()
            toolbox.add_toolbar(_('Adjust'), adjust_toolbar)
            toolbox.show()
            toolbox.set_current_toolbar(1)
            self.toolbar = primary_toolbar

        if HAVE_TOOLBOX:
            # toolbox.toolbar.insert(record_toolbar_button, -1)
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

        if HAVE_TOOLBOX:
            separator_factory(toolbox.toolbar, True, False)

            stop_button = StopButton(self)
            stop_button.props.accelerator = '<Ctrl>q'
            toolbox.toolbar.insert(stop_button, -1)
            stop_button.show()

    def _destroy_cb(self, win, event):
        ''' Clean up on the way out. '''
        gtk.main_quit()

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
        _logger.debug('found %d starred items', self._nobjects)
        for dsobj in self.dsobjects:
            slide = self._uid_to_slide(dsobj.object_id)
            owner = self._buddies[0]
            title = ''
            desc = ''
            preview = None
            if hasattr(dsobj, 'metadata'):
                if 'title' in dsobj.metadata:
                    title = dsobj.metadata['title']
                if 'description' in dsobj.metadata:
                    desc = dsobj.metadata['description']
                if 'mime_type' in dsobj.metadata and \
                   dsobj.metadata['mime_type'][0:5] == 'image':
                    preview = get_pixbuf_from_file(dsobj.file_path,
                                                   int(PREVIEWW * self._scale),
                                                   int(PREVIEWH * self._scale))
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
                                         desc))
            else:
                slide.title = title
                slide.preview = preview
                slide.description = desc
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
            self._send_event('R:rescanning')
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
        dsobject.metadata['activity'] = 'org.laptop.sugar.ReadActivity'
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

        if len(self._slides) == 0:
            self._prev.set_image(self.prev_off_pixbuf)
            self._next.set_image(self.next_off_pixbuf)
            self._description.set_label(
                _('Do you have any items in your Journal starred?'))
            self._help.set_layer(TOP)
            self._description.set_layer(MIDDLE)
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
        if self.i == len(self._slides) - 1:
            self._next.set_image(self.next_off_pixbuf)
        else:
            self._next.set_image(self.next_pixbuf)

        pixbuf = slide.preview

        if pixbuf is not None:
            self._preview.set_shape(pixbuf.scale_simple(
                    int(PREVIEWW * self._scale),
                    int(PREVIEWH * self._scale),
                    gtk.gdk.INTERP_NEAREST))
            self._preview.set_layer(MIDDLE)
        else:
            if self._preview is not None:
                self._preview.hide()

        self._title.set_label(slide.title)
        self._title.set_layer(MIDDLE)

        self._description.set_label(slide.description)
        self._description.set_layer(MIDDLE)

        if self.initiating is None or self.initiating:
            if slide.sound is None:
                slide.sound = self._search_for_audio_note(slide.uid)
            if slide.sound is not None:
                if self._playing:
                    _logger.debug('Playing audio note')
                    gobject.idle_add(play_audio_from_file,
                                     slide.sound.file_path)
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
        self._prev.set_layer(DRAG)
        self._next.set_layer(DRAG)
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
                pixbuf_thumb = slide.preview.scale_simple(int(w), int(h),
                                                          gtk.gdk.INTERP_TILES)
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

    def _add_text_no_changed_cb(self, widget=None, event=None):
        pass

    def _text_focus_out_cb(self, widget=None, event=None):
        bounds = self.text_entry.get_buffer().get_bounds()
        s = self.text_entry.get_buffer().get_text(bounds[0], bounds[1])
        self._selected_spr.set_label(s)
        self._saved_string = self._selected_spr.labels[0]

    def _button_press_cb(self, win, event):
        ''' The mouse button was pressed. Is it on a thumbnail sprite? '''
        x, y = map(int, event.get_coords())

        self._dragpos = [x, y]
        self._total_drag = [0, 0]

        spr = self._sprites.find_sprite((x, y))
        if spr is not None:
            self._startpos = spr.get_xy()
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
                    label = '%s\n[%s] ' % (self._selected_spr.labels[0],
                                             profile.get_nick_name())
                else:
                    label = self._selected_spr.labels[0]
                self._selected_spr.set_label(label)
            elif spr.type == 'title':
                if self.initiating is None or self.initiating:
                    label = self._selected_spr.labels[0]
                    self._selected_spr.set_label(label)
                else:
                    self._selected_spr = None
            if not hasattr(self, 'text_entry'):
                self.text_entry = gtk.TextView()
                self.text_entry.set_justification(gtk.JUSTIFY_CENTER)
                self.text_entry.set_pixels_above_lines(4)
                self.text_buffer = gtk.TextBuffer()
                self.fixed.put(self.text_entry, 0, 0)
                '''
                NOTE: Use override_background_color in GTK3 port to set
                transparent background.
                '''
            self.text_entry.show()
            self.text_buffer.set_text(self._saved_string)
            self.text_entry.set_buffer(self.text_buffer)
            w = spr.label_safe_width()
            h = spr.label_safe_height()
            self.text_entry.set_size_request(w, h)
            bx, by = spr.get_xy()
            mx, my = spr.label_left_top()
            if self._tablet_mode():
                self.fixed.move(self.text_entry, bx + mx, 0)
            else:
                self.fixed.move(self.text_entry, bx + mx, by + my * 2)
            self.fixed.show()
            self.text_entry.connect('focus-out-event', self._text_focus_out_cb)
            self.text_entry.grab_focus()
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
        slide.star.set_layer(DRAG+1)
        return False

    def _mouse_move_cb(self, win, event):
        ''' Drag a thumbnail with the mouse. '''
        spr = self._press
        if spr is None:
            self._dragpos = [0, 0]
            return False
        # win.grab_focus()
        x, y = map(int, event.get_coords())
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
        # win.grab_focus()
        self._dragpos = [0, 0]
        x, y = map(int, event.get_coords())

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
            self._record_button.set_image(self.record_pixbuf)
            self._record_button.type = 'record'
            self._record_button.set_layer(DRAG)
            self._playback_button.set_image(self.playback_pixbuf)
            self._playback_button.type = 'play'
            self._playback_button.set_layer(DRAG)
            # Autosave if there was not already a recording
            slide = self._slides[self.i]
            _logger.debug('Autosaving recording')
            self._notify_successful_save(title=_('Save recording'))
            gobject.timeout_add(100, self._wait_for_transcoding_to_finish)
        else:  # Wasn't recording, so start
            _logger.debug('recording...False. Start recording.')
            self._record_button.set_image(self.recording_pixbuf)
            self._record_button.type = 'recording'
            self._record_button.set_layer(DRAG)
            self._grecord.record_audio()
            self._recording = True

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
        self._playback_button.set_image(self.playing_pixbuf)
        self._playback_button.set_layer(DRAG)
        self._playback_button.type = 'playing'
        gobject.timeout_add(1000, self._playback_button_reset)
        gobject.idle_add(play_audio_from_file,
                         self._slides[self.i].sound.file_path)

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
            jobject.metadata['title'] = slide.title
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
            self.text_entry.hide()

        if self._selected_spr is not None:
            slide = self._slides[self.i]
            if self._selected_spr.type == 'title':
                slide.title = self._selected_spr.labels[0]
                if self.initiating is not None and self.initiating:
                    self._send_event('t:%s' % (self._data_dumper(
                                [slide.uid, slide.title])))
            else:
                slide.description = self._selected_spr.labels[0]
                if self.initiating is not None:
                    self._send_event('d:%s' % (self._data_dumper(
                                [slide.uid, slide.description])))
            _logger.debug('marking %d as dirty' % (self.i))
            slide.dirty = True
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

    def _dump(self, slide):
        ''' Dump data for sharing.'''
        _logger.debug('dumping %s' % (slide.uid))
        if slide.preview is None:
            data = [slide.uid, slide.title, None, slide.description]
        else:
            data = [slide.uid, slide.title,
                    pixbuf_to_base64(activity, slide.preview,
                                     width=300, height=225),
                    slide.description]
        return self._data_dumper(data)

    def _data_dumper(self, data):
        if _OLD_SUGAR_SYSTEM:
            return json.write(data)
        else:
            io = StringIO()
            jdump(data, io)
            return io.getvalue()

    def _load(self, data):
        ''' Load slide data from a sharer. '''
        self._restore_cursor()
        uid, title, base64, description = self._data_loader(data)
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
                                      description))
        else:
            _logger.debug('updating description for %s' % (uid))
            slide = self._uid_to_slide(uid)
            slide.title = title
            if base64 is None:
                slide.preview = None
            else:
                slide.preview = base64_to_pixbuf(activity, base64)
            slide.description = description
            slide.active = True
            if not slide.fav:
                slide.fav = True
                if slide.star is not None:
                    slide.star.set_shape(self._fav_pixbuf)
                    slide.star.type = 'star'
        if not self._thumbnail_mode:
            self._thumb_button.set_active(True)
        else:
            self._show_thumbs()

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
        for slide in self._slides:
            slide.active = False
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
                self._share_nick()

    def event_received_cb(self, text):
        ''' Data is passed as tuples: cmd:text '''
        dispatch_table = {'s': self._load,
                          'c': self._update_colors,
                          'd': self._update_description,
                          't': self._update_title,
                          'S': self._update_star,
                          'R': self._reset,
                          'j': self._new_join,
                          }
        _logger.debug('<<< %s' % (text[0]))
        dispatch_table[text[0]](text[2:])

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
        if colors[0] != self._colors[0] or \
           colors[1] != self._colors[1]:
            self._colors = colors[:]
            self._my_canvas.set_image(svg_str_to_pixbuf(
                genblank(self._width, self._height, [self._colors[0],
                                                     self._colors[0]])))
            self._description.set_image(svg_str_to_pixbuf(
                    genblank(
                        int(self._descriptionwh[0]),
                        int(self._descriptionwh[1]),
                        self._colors)))
            self._title.set_image(svg_str_to_pixbuf(
                        genblank(int(self._titlewh[0]),
                                 int(self._titlewh[1]),
                                 self._colors)))

    def _update_description(self, data):
        uid, text = self._data_loader(data)
        slide = self._uid_to_slide(uid)
        if slide is None:
            _logger.debug('slide %s not found' % (uid))
            return
        _logger.debug('updating description %s' % (uid))
        slide.description = text
        if self.i == self._slides.index(slide):
            self._description.set_label(text)
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

    def _share_nick(self):
        _logger.debug('sharing nick')
        self._send_event('j:%s' % (profile.get_nick_name()))

    def _share_colors(self):
        _logger.debug('sharing colors')
        self._send_event('c:%s' % (self._data_dumper(self._colors)))

    def _share_slides(self):
        for slide in self._slides:
            if slide.active and slide.fav:
                _logger.debug('sharing %s' % (slide.uid))
                gobject.idle_add(self._send_event, 's:%s' % (
                        str(self._dump(slide))))

    def _send_star(self, uid, status):
        _logger.debug('sharing star for %s (%s)' % (uid, str(status)))
        self._send_event('S:%s' % (self._data_dumper([uid, status])))

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
