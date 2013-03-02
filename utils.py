# -*- coding: utf-8 -*-
#Copyright (c) 2011-13 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA


from gi.repository import GdkPixbuf
import os
import subprocess

from gettext import gettext as _

XO1 = 'xo1'
XO15 = 'xo1.5'
XO175 = 'xo1.75'
XO4 = 'xo4'
UNKNOWN = 'unknown'


def get_tablet_mode():
    if not os.path.exists('/dev/input/event4'):
        return False
    try:
        output = subprocess.call(
            ['evtest', '--query', '/dev/input/event4', 'EV_SW',
             'SW_TABLET_MODE'])
    except (OSError, subprocess.CalledProcessError):
        return False
    if str(output) == '10':
        return True
    return False


def get_hardware():
    ''' Determine whether we are using XO 1.0, 1.5, ... or 'unknown'
    hardware '''
    version = _get_dmi('product_version')
    # product = _get_dmi('product_name')
    if version is None:
        hwinfo_path = '/bin/olpc-hwinfo'
        if os.path.exists(hwinfo_path) and os.access(hwinfo_path, os.X_OK):
            model = check_output([hwinfo_path, 'model'], 'unknown hardware')
            version = model.strip()
    if version == '1':
        return XO1
    elif version == '1.5':
         return XO15
    elif version == '1.75':
        return XO175
    elif version == '4':
        return XO4
    else:
        # Some systems (e.g. ARM) don't have dmi info
        if os.path.exists('/sys/devices/platform/lis3lv02d/position'):
            return XO175        
        elif os.path.exists('/etc/olpc-release'):
            return XO1
        else:
            return UNKNOWN


def _get_dmi(node):
    ''' The desktop management interface should be a reliable source
    for product and version information. '''
    path = os.path.join('/sys/class/dmi/id', node)
    try:
        return open(path).readline().strip()
    except:
        return None


def check_output(command, warning):
    ''' Workaround for old systems without subprocess.check_output'''
    output = None
    try:
        output = subprocess.check_output(command)
    except subprocess.CalledProcessError:
        print(warning)
    return output


def parse_comments(comments):
    label = ''
    for comment in comments:
        if 'from' in comment:
            label += '[%s] ' % (comment['from'])
        if 'message' in comment:
            label += comment['message']
        label += '\n'
    return label


def get_path(activity, subpath):
    """ Find a Rainbow-approved place for temporary files. """
    try:
        return(os.path.join(activity.get_activity_root(), subpath))
    except:
        # Early versions of Sugar didn't support get_activity_root()
        return(os.path.join(os.environ['HOME'], ".sugar/default",
                            "org.sugarlabs.PortfolioActivity", subpath))


def rgb(color):
    return float(int(color[1:3], 16) / 255.), \
           float(int(color[3:5], 16) / 255.), \
           float(int(color[5:7], 16) / 255.)

def _luminance(color):
    ''' Calculate luminance value '''
    return int(color[1:3], 16) * 0.3 + int(color[3:5], 16) * 0.6 + \
           int(color[5:7], 16) * 0.1


def lighter_color(colors):
    ''' Which color is lighter? Use that one for the text background '''
    if _luminance(colors[0]) > _luminance(colors[1]):
        return 0
    return 1


def svg_str_to_pixbuf(svg_string):
    ''' Load pixbuf from SVG string '''
    pl = GdkPixbuf.PixbufLoader()
    pl.write(svg_string)
    pl.close()
    pixbuf = pl.get_pixbuf()
    return pixbuf


def svg_rectangle(width, height, colors):
    ''' Generate a rectangle frame in two colors '''
    return \
'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\
<svg\
   version="1.1"\
   width="%f"\
   height="%f">\
    <g>\
      <rect\
         width="%f"\
         height="%f"\
         x="2.5"\
         y="2.5"\
         style="fill:none;stroke:%s;stroke-width:5;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-opacity:1;stroke-dasharray:none" />\
      <rect\
         width="%f"\
         height="%f"\
         x="7.5"\
         y="7.5"\
         style="fill:none;stroke:%s;stroke-width:5;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-opacity:1;stroke-dasharray:none" />\
    </g>\
</svg>' % (width, height,
           width - 5, height - 5, colors[1],
           width - 15, height - 15, colors[0])


def load_svg_from_file(file_path, width, height):
    '''Create a pixbuf from SVG in a file. '''
    return GdkPixbuf.Pixbuf.new_from_file_at_size(file_path, width, height)


def file_to_base64(activity, path):
    ''' Given a file, convert its contents to base64 '''
    base64 = os.path.join(get_path(activity, 'instance'), 'base64tmp')
    cmd = 'base64 <' + path + ' >' + base64
    subprocess.check_call(cmd, shell=True)
    file_handle = open(base64, 'r')
    data = file_handle.read()
    file_handle.close()
    os.remove(base64)
    return data


def pixbuf_to_base64(activity, pixbuf, width=100, height=75):
    ''' Convert pixbuf to base64-encoded data '''
    png_file = os.path.join(get_path(activity, 'instance'), 'imagetmp.png')
    if pixbuf != None:
        pixbuf = pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.NEAREST)
        pixbuf.savev(png_file, "png", [], [])
    data = file_to_base64(activity, png_file)
    os.remove(png_file)
    return data


def base64_to_file(activity, data, path):
    ''' Given a file, convert its contents from base64 '''
    base64 = os.path.join(get_path(activity, 'instance'), 'base64tmp')
    file_handle = open(base64, 'w')
    file_handle.write(data)
    file_handle.close()
    cmd = 'base64 -d <' + base64 + '>' + path
    subprocess.check_call(cmd, shell=True)
    os.remove(base64)


def base64_to_pixbuf(activity, data, width=300, height=225):
    ''' Convert base64-encoded data to a pixbuf '''
    png_file = os.path.join(get_path(activity, 'instance'), 'imagetmp.png')
    base64_to_file(activity, data, png_file)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(png_file, width, height)
    os.remove(png_file)
    return pixbuf


def get_pixbuf_from_journal(dsobject, w, h):
    """ Load a pixbuf from a Journal object. """
    pixbufloader = \
        GdkPixbuf.PixbufLoader.new_with_mime_type('image/png')
    pixbufloader.set_size(min(300, int(w)), min(225, int(h)))
    try:
        pixbufloader.write(dsobject.metadata['preview'])
        pixbuf = pixbufloader.get_pixbuf()
    except:
        pixbuf = None
    pixbufloader.close()
    return pixbuf


def get_pixbuf_from_file(file_path, w, h):
    """ Load a pixbuf from a file. """
    return GdkPixbuf.Pixbuf.new_from_file_at_size(file_path, w, h)


def genblank(w, h, colors, stroke_width=1.0):
    svg = SVG()
    svg.set_colors(colors)
    svg.set_stroke_width(stroke_width)
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
        self.set_stroke_width(self._stroke_width)
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
