#!/usr/bin/python -tt

# bblib v1.0
# Very basic, mostly undocumented interface to BetaBrite LED signs.
#
# Copyright (c) 2008, John Morrissey <jwm@horde.net>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import cPickle

_HEADER_START = '\0\0\0\0\0\001'
_DATA_START = '\002'
_DATA_END = '\004'
_TYPE_ALL_SIGNS = 'Z'
_ADDR_ALL_SIGNS = '00'

_COMMAND_WRITE_SPECIALFUNC = 'E'
_COMMAND_SET_MEMORY_CONFIG = '$'
FILE_TYPE_TEXT = 'A'
FILE_TYPE_STRING = 'B'
TEXT_FILE_START_TIME_ALWAYS = 'FF'
TEXT_FILE_STOP_TIME_ALWAYS = '00'
FILE_UNLOCKED = 'U'
FILE_LOCKED = 'L'
_STRING_FILE_NULL_TIMES = '0000'

_COMMAND_WRITE_STRING = 'G'

_COMMAND_WRITE_TEXT = 'A'
_TEXT_MODE_START = '\x1b'
_TEXT_POSITION_CENTER_VERT = ' '
TEXT_MODES = { 
	'rotate': 'a',
	'hold': 'b',
	'flash': 'c',
	'rollup': 'e',
	'rolldown': 'f',
	'rollleft': 'g',
	'rollright': 'h',
	'wipeup': 'i',
	'wipedown': 'j',
	'wipeleft': 'k',
	'wiperight': 'l',
	'scroll': 'm',
	'auto': 'o',
	'rollin': 'p',
	'rollout': 'q',
	'wipein': 'r',
	'wipeout': 's',
	'crotate': 't',
	'explode': 'u',
	'clock': 'v',
	'twinkle': 'n0',
	'sparkle': 'n1',
	'snow': 'n2',
	'interlock': 'n3',
	'switch': 'n4',
	'spray': 'n6',
	'starburst': 'n7',
	'welcome': 'n8',
	'slot': 'n9',
	'cycle': 'nc',
}

_TEXT_COLOR_START = '\x1c'
TEXT_COLORS = {
	'red': '1',
	'green': '2',
	'amber': '3',
	'dimred': '4',
	'dimgreen': '5',
	'brown': '6',
	'orange': '7',
	'yellow': '8',
	'rainbow1': '9',
	'rainbow2': 'a',
	'mix': 'b',
	'auto': 'c',
}

TEXT_FILENAMES = [
	'A',
	# FIXME: there are more
]
STRING_FILENAMES = [
	'1',
	# FIXME: there are more
]

CONFDIR = 'bbppl_config'

def get_settings(who):
	global CONFDIR
		
	try:
		fd = open('%s/%s.pkl' % (CONFDIR, who), 'r')
		data = cPickle.load(fd)
		fd.close()
	except:
		return {
			'color': 'auto',
			'mode': 'hold',
		}

	return data

def set_settings(who, **kw):
	global CONFDIR

	data = get(who)

	for param in ['color', 'mode']:
		if kw.get(param):
			data[param] = kw[param]

	fd = open('%s/%s.pkl' % (CONFDIR, who), 'w')
	cPickle.dump(data, fd, 2)
	fd.close()

class FileConfig:
	def __init__(self, name, type=FILE_TYPE_TEXT, size='0400',
		locked=FILE_LOCKED,
		start=TEXT_FILE_START_TIME_ALWAYS,
		stop=TEXT_FILE_STOP_TIME_ALWAYS):

		if type == FILE_TYPE_TEXT:
			global TEXT_FILENAMES
			if name not in TEXT_FILENAMES:
				raise Exception('Invalid text file name: "%s"' % name)
		elif type == FILE_TYPE_STRING:
			global STRING_FILENAMES
			if name not in STRING_FILENAMES:
				raise Exception('Invalid string file name: "%s"' % name)

		self.name = name
		self.type = type
		self.size = size
		self.locked = locked
		if type == FILE_TYPE_TEXT:
			self.start = start
			self.stop = stop
		else:
			self.start = '00'
			self.stop = '00'

def set_memory_config(file_configs):
	global STRING_FILENAMES, TEXT_FILENAMES
	global _HEADER_START, _TYPE_ALL_SIGNS, _ADDR_ALL_SIGNS, \
		_DATA_START, _COMMAND_WRITE_SPECIALFUNC, \
		_COMMAND_SET_MEMORY_CONFIG, \
		FILE_TYPE_TEXT, FILE_TYPE_STRING, \
		_STRING_FILE_NULL_TIMES, _DATA_END

	cmd = '%s%s%s%s%s%s' % (
		_HEADER_START, _TYPE_ALL_SIGNS, _ADDR_ALL_SIGNS,
		_DATA_START, _COMMAND_WRITE_SPECIALFUNC,
		_COMMAND_SET_MEMORY_CONFIG
	)

	for c in file_configs:
		if c.type == FILE_TYPE_TEXT:
			cmd += '%s%s%s%s%s%s' % (
				c.name, c.type, c.locked, c.size,
				c.start, c.stop
			)
		elif c.type == FILE_TYPE_STRING:
			cmd += '%s%s%s%s%s' % (
				c.name, c.type, c.locked, c.size,
				_STRING_FILE_NULL_TIMES
			)
	cmd += _DATA_END

	fp = open('/dev/cua00', 'w')
	fp.write(cmd)
	fp.close()

def set_string_file(file, data):
	global STRING_FILENAMES
	global _HEADER_START, _TYPE_ALL_SIGNS, _ADDR_ALL_SIGNS, \
		_DATA_START, _COMMAND_WRITE_STRING, _DATA_END

	if file not in STRING_FILENAMES:
		raise Exception('Invalid file: "%s"' % file)

	cmd = '%s%s%s%s%s%s%s%s' % (
		_HEADER_START, _TYPE_ALL_SIGNS, _ADDR_ALL_SIGNS,
		_DATA_START, _COMMAND_WRITE_STRING,
		file, data, _DATA_END
	)

	fp = open('/dev/cua00', 'w')
	fp.write(cmd)
	fp.close()

def set_text_file(file, data, mode='wipeup', color='green'):
	global TEXT_FILENAMES
	global _HEADER_START, _TYPE_ALL_SIGNS, _ADDR_ALL_SIGNS, \
		_DATA_START, _COMMAND_WRITE_TEXT, \
		_TEXT_MODE_START, _TEXT_POSITION_CENTER_VERT, \
		_TEXT_COLOR_START, _DATA_END
	global TEXT_MODES, TEXT_COLORS

	if file not in TEXT_FILENAMES:
		raise Exception('Invalid file: "%s"' % file)

	cmd = '%s%s%s%s%s%s%s%s%s%s%s%s%s' % (
		_HEADER_START, _TYPE_ALL_SIGNS, _ADDR_ALL_SIGNS,
		_DATA_START,
		_COMMAND_WRITE_TEXT, file,
		_TEXT_MODE_START, _TEXT_POSITION_CENTER_VERT,
		TEXT_MODES[mode],
		_TEXT_COLOR_START, TEXT_COLORS[color],
		data, _DATA_END
	)

	fp = open('/dev/cua00', 'w')
	fp.write(cmd)
	fp.close()
