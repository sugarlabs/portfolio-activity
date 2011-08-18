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

from math import sqrt

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

from sprites import Sprites, Sprite
from exporthtml import save_html
from utils import get_path, lighter_color, svg_str_to_pixbuf, \
    button_factory, separator_factory, combo_factory, label_factory, \
    get_pixbuf_from_journal, genblank, get_hardware

from gettext import gettext as _

import logging
_logger = logging.getLogger("portfolio-activity")

try:
    from sugar.graphics import style
    GRID_CELL_SIZE = style.GRID_CELL_SIZE
except ImportError:
    GRID_CELL_SIZE = 0

# Size and position of title, preview image, and description
PREVIEWW = 450
PREVIEWH = 338
PREVIEWY = 80
TITLEH = 60
DESCRIPTIONH = 350
DESCRIPTIONX = 50
DESCRIPTIONY = 450
# If the entry is an image, it is used instead of the preview
# and shown at a larger size...
FULLW = 800
FULLH = 600
# ...leaving less room for a description.
SHORTH = 100
SHORTX = 50
SHORTY = 700

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
DRAG = 5
TOP = 4
UNDRAG = 3
MIDDLE = 2
BOTTOM = 1
HIDE = 0


class PortfolioActivity(activity.Activity):
    ''' Make a slideshow from starred Journal entries. '''

    def __init__(self, handle):
        ''' Initialize the toolbars and the work surface '''
        super(PortfolioActivity, self).__init__(handle)

        self._tmp_path = get_path(activity, 'instance')

        self._hw = get_hardware()

        self._setup_toolbars()
        self._setup_canvas()
        self._setup_workspace()

        self._thumbs = []
        self._thumbnail_mode = False

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
        self._canvas.add_events(gtk.gdk.POINTER_MOTION_MASK)
        self._canvas.add_events(gtk.gdk.BUTTON_RELEASE_MASK)
        self._canvas.add_events(gtk.gdk.KEY_PRESS_MASK)
        self._canvas.connect("expose-event", self._expose_cb)
        self._canvas.connect("button-press-event", self._button_press_cb)
        self._canvas.connect("button-release-event", self._button_release_cb)
        self._canvas.connect("motion-notify-event", self._mouse_move_cb)

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

        if self._hw[0:2] == 'xo':
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
        self._description2.set_label_attributes(
            int(descriptionf * self._scale))

        self._my_canvas = Sprite(self._sprites, 0, 0,
                                gtk.gdk.Pixmap(self._canvas.window,
                                               self._width,
                                               self._height, -1))
        self._my_gc = self._my_canvas.images[0].new_gc()
        self._my_canvas.set_layer(BOTTOM)

        self._clear_screen()

        self._find_starred()
        self.i = 0
        self._show_slide()

        self._playing = False
        self._rate = 10

    def _setup_toolbars(self):
        ''' Setup the toolbars. '''

        self.max_participants = 1  # no sharing

        if HAVE_TOOLBOX:
            toolbox = ToolbarBox()

            # Activity toolbar
            activity_button = ActivityToolbarButton(self)

            toolbox.toolbar.insert(activity_button, 0)
            activity_button.show()

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

        self._prev_button = button_factory(
            'go-previous-inactive', _('Prev slide'), self._prev_cb,
            self.toolbar, accelerator='<Ctrl>P')

        self._next_button = button_factory(
            'go-next', _('Next slide'), self._next_cb,
            self.toolbar, accelerator='<Ctrl>N')

        separator_factory(self.toolbar)

        self._auto_button = button_factory(
            'media-playlist-repeat', _('Autoplay'), self._autoplay_cb,
            self.toolbar)

        if HAVE_TOOLBOX:
            toolbox.toolbar.insert(adjust_toolbar_button, -1)

        label = label_factory(_('Adjust playback speed'), adjust_toolbar)
        label.show()

        self._unit_combo = combo_factory(UNITS, TEN,
                                        _('Adjust playback speed'),
                                        self._unit_combo_cb, adjust_toolbar)
        self._unit_combo.show()

        separator_factory(self.toolbar)

        self._thumb_button = button_factory(
            'thumbs-view', _('Thumbnail view'),
            self._thumbs_cb, self.toolbar)

        button_factory('view-fullscreen', _('Fullscreen'),
                       self.do_fullscreen_cb, self.toolbar,
                       accelerator='<Alt>Return')

        separator_factory(self.toolbar)

        self._save_button = button_factory(
            'save-as-html', _('Save as HTML'),
            self._save_as_html_cb, self.toolbar)

        if HAVE_TOOLBOX:
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
        ''' Clean up on the way out. '''
        gtk.main_quit()

    def _find_starred(self):
        ''' Find all the favorites in the Journal. '''
        self._dsobjects, self._nobjects = datastore.find({'keep': '1'})
        return

    def _prev_cb(self, button=None):
        ''' The previous button has been clicked; goto previous slide. '''
        if self.i > 0:
            self.i -= 1
            self._show_slide()

    def _next_cb(self, button=None):
        ''' The next button has been clicked; goto next slide. '''
        if self.i < self._nobjects - 1:
            self.i += 1
            self._show_slide()

    def _autoplay_cb(self, button=None):
        ''' The autoplay button has been clicked; step through slides. '''
        if self._playing:
            self._stop_autoplay()
        else:
            if self._thumbnail_mode:
                self._set_view_mode(self._current_slide)
            self._playing = True
            self._auto_button.set_icon('media-playback-pause')
            self._loop()

    def _stop_autoplay(self):
        ''' Stop autoplaying. '''
        self._playing = False
        self._auto_button.set_icon('media-playlist-repeat')
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

    def _bump_test(self):
        ''' Test for accelerometer event (XO 1.75 only). '''
        fh = open('/sys/devices/platform/lis3lv02d/position')
        string = fh.read()
        xyz = string[1:-2].split(',')
        dx = int(xyz[0])
        fh.close()
        
        if dx > 250:
            self.i += 1
            if self.i == self._nobjects:
                self.i = 0
            self._show_slide()
        elif dx < -250:
            self.i -= 1
            if self.i < 0:
                self.i = self._nobjects - 1
            self._show_slide()
        elif not self._thumbnail_mode:
            self._bump_id = gobject.timeout_add(int(100), self._bump_test)

    def _save_as_html_cb(self, button=None):
        ''' Export an HTML version of the slideshow to the Journal. '''
        self._save_button.set_icon('save-in-progress')
        results = save_html(self._dsobjects, profile.get_nick_name(),
                            self._colors, self._tmp_path)
        html_file = os.path.join(self._tmp_path, 'tmp.html')
        tmp_file = open(html_file, 'w')
        tmp_file.write(results)
        tmp_file.close()

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
                            'save-as-html')
        return

    def _clear_screen(self):
        ''' Clear the screen to the darker of the two XO colors. '''
        self._my_gc.set_foreground(
            self._my_gc.get_colormap().alloc_color(self._colors[0]))
        self._my_canvas.images[0].draw_rectangle(self._my_gc, True, 0, 0,
                                                 self._width, self._height)
        self._title.hide()
        self._full_screen.hide()
        self._preview.hide()
        self._description.hide()
        if hasattr(self, '_thumbs'):
            for thumbnail in self._thumbs:
                thumbnail[0].hide()
        self.invalt(0, 0, self._width, self._height)

        # Reset drag settings
        self._press = None
        self._release = None
        self._dragpos = [0, 0]
        self._total_drag = [0, 0]
        self.last_spr_moved = None

    def _show_slide(self):
        ''' Display a title, preview image, and decription for slide i. '''
        self._clear_screen()

        if self._nobjects == 0:
            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')
            self._description.set_label(
                _('Do you have any items in your Journal starred?'))
            self._description.set_layer(MIDDLE)
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
                self._dsobjects[self.i].file_path, int(PREVIEWW * self._scale),
                int(PREVIEWH * self._scale))
            media_object = True
        except:
            pixbuf = get_pixbuf_from_journal(self._dsobjects[self.i], 300, 225)

        if pixbuf is not None:
            if not media_object:
                self._preview.images[0] = pixbuf.scale_simple(
                    int(PREVIEWW * self._scale),
                    int(PREVIEWH * self._scale),
                    gtk.gdk.INTERP_TILES)
                self._full_screen.hide()
                self._preview.set_layer(MIDDLE)
            else:
                self._full_screen.images[0] = pixbuf.scale_simple(
                    int(FULLW * self._scale),
                    int(FULLH * self._scale),
                    gtk.gdk.INTERP_TILES)
                self._full_screen.set_layer(MIDDLE)
                self._preview.hide()
        else:
            if self._preview is not None:
                self._preview.hide()
                self._full_screen.hide()

        self._title.set_label(self._dsobjects[self.i].metadata['title'])
        self._title.set_layer(MIDDLE)

        if 'description' in self._dsobjects[self.i].metadata:
            if media_object:
                self._description2.set_label(
                    self._dsobjects[self.i].metadata['description'])
                self._description2.set_layer(MIDDLE)
                self._description.set_label('')
                self._description.hide()
            else:
                self._description.set_label(
                    self._dsobjects[self.i].metadata['description'])
                self._description.set_layer(MIDDLE)
                self._description2.set_label('')
                self._description2.hide()
        else:
            self._description.set_label('')
            self._description.hide()
            self._description2.set_label('')
            self._description2.hide()
        if self._hw == XO175:
            self._bump_id = gobject.timeout_add(int(500), self._bump_test)

    def _thumbs_cb(self, button=None):
        ''' Toggle between thumbnail view and slideshow view. '''
        if self._thumbnail_mode:
            self._set_view_mode(self._current_slide)
            self._show_slide()
        else:
            self._stop_autoplay()
            self._current_slide = self.i
            self._thumbnail_mode = True
            self._clear_screen()

            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')
            self._thumb_button.set_icon('slide-view')
            self._thumb_button.set_tooltip(_('Slide view'))

            n = int(sqrt(self._nobjects) + 0.5)
            w = int(self._width / n)
            h = int(w * 0.75)  # maintain 4:3 aspect ratio
            x_off = int((self._width - n * w) / 2)
            x = x_off
            y = 0
            for i in range(self._nobjects):
                self.i = i
                self._show_thumb(x, y, w, h)
                x += w
                if x + w > self._width:
                    x = x_off
                    y += h
            self.i = 0  # Reset position in slideshow to the beginning
        return False

    def _show_thumb(self, x, y, w, h):
        ''' Display a preview image and title as a thumbnail. '''

        if len(self._thumbs) < self.i + 1:
            # Create a Sprite for this thumbnail
            pixbuf = None
            try:
                pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                    self._dsobjects[self.i].file_path, int(w), int(h))
            except:
                pixbuf = get_pixbuf_from_journal(self._dsobjects[self.i],
                                                 int(w), int(h))
            pixbuf_thumb = pixbuf.scale_simple(int(w), int(h),
                                               gtk.gdk.INTERP_TILES)

            self._thumbs.append([Sprite(self._sprites, x, y, pixbuf_thumb),
                                 x, y, self.i])
            self._thumbs[-1][0].set_label(str(self.i + 1))
        self._thumbs[self.i][0].set_layer(TOP)

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
        win.grab_focus()
        x, y = map(int, event.get_coords())

        self._dragpos = [x, y]
        self._total_drag = [0, 0]

        spr = self._sprites.find_sprite((x, y))
        self._press = None
        self._release = None

        # Are we clicking on a thumbnail?
        if not self._spr_is_thumbnail(spr):
            return False

        _logger.debug('found a thumbnail')
        self.last_spr_moved = spr
        self._press = spr
        self._press.set_layer(DRAG)
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
        self._dragpos = [x, y]
        self._total_drag[0] += dx
        self._total_drag[1] += dy
        return False

    def _button_release_cb(self, win, event):
        ''' Button event is used to swap slides or goto next slide. '''
        win.grab_focus()
        self._dragpos = [0, 0]
        x, y = map(int, event.get_coords())

        if self._thumbnail_mode:
            # Drop the dragged thumbnail below the other thumbnails so
            # that you can find the thumbnail beneath it.
            self._press.set_layer(UNDRAG)
            i = self._spr_to_thumb(self._press)
            spr = self._sprites.find_sprite((x, y))
            if self._spr_is_thumbnail(spr):
                self._release = spr
                # If we found a thumbnail and it is not the one we
                # dragged, swap their positions.
                if not self._press == self._release:
                    j = self._spr_to_thumb(self._release)
                    self._thumbs[i][0] = self._release
                    self._thumbs[j][0] = self._press
                    tmp = self._dsobjects[i]
                    self._dsobjects[i] = self._dsobjects[j]
                    self._dsobjects[j] = tmp
                    self._thumbs[j][0].move((self._thumbs[j][1],
                                             self._thumbs[j][2]))
            self._thumbs[i][0].move((self._thumbs[i][1], self._thumbs[i][2]))
            self._press.set_layer(TOP)
            self._press = None
            self._release = None
        else:
            self._next_cb()
        return False

    def _set_view_mode(self, i):
        ''' Switch to slide-viewing mode. '''
        self._thumbnail_mode = False
        self.i = i
        self._thumb_button.set_icon('thumbs-view')
        self._thumb_button.set_tooltip(_('Thumbnail view'))

    def _unit_combo_cb(self, arg=None):
        ''' Read value of predefined conversion factors from combo box '''
        if hasattr(self, '_unit_combo'):
            active = self._unit_combo.get_active()
            if active in UNIT_DICTIONARY:
                self._rate = UNIT_DICTIONARY[active][1]
