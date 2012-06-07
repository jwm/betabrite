#!/usr/bin/python -tt
from __future__ import with_statement

# twitter2bbsign v2.0
# Interfaces with Twitter, Google Calendar, and arbitrary RSS feeds to
# display messages on a BetaBrite sign.
#
# Copyright (c) 2008-9, John Morrissey <jwm@horde.net>
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

# Depends on: Python 2.5+python-simplejson or Python 2.6+, gdata,
# python-feedparser, twisted.

# FIXME: Twitter support is completely broken since the Twitter API
# requires OAuth now.

# Permanent messages that never expire.
PERM_MSGS = [
]
# How many items (excluding PERM_MSGS) are in the queue before it's
# considered "full?"
QUEUE_FULL = 10
# How long each message should be displayed on the sign, in seconds.
MSG_DISPLAY_TIME = 4
# Loop once through messages younger than this (in seconds) when new
# message(s) arrive.
NEW_MSG_QUICK_LOOP_AGE = 60 * 2
# How often messages stay in the queue, in seconds, when the queue has fewer
# than QUEUE_FULL messages in it.
QUEUE_UNDERFULL_LIFETIME = 2 * 60 * 60
# How often messages stay in the queue, in seconds, when the queue has more
# than QUEUE_FULL messages in it.
QUEUE_FULL_LIFETIME = 30 * 60

# Twitter credentials.
TWITTER_USER = ''
TWITTER_PASS = ''
# How often to poll Twitter for new messages, in seconds.
TWITTER_POLL_INTERVAL = 5
# How often to poll Google Calendar for new events, in seconds.
GCAL_POLL_INTERVAL = 60
# URL for the Google Calendar to poll for events.
GCAL_CALENDAR_URL = ''
# How often to poll RSS feeds for random events.
RSS_POLL_INTERVAL = 30 * 60

from base64 import b64encode
import cPickle
from datetime import date, timedelta
from httplib import HTTPConnection
import os
from random import randrange
import re
import sys
import thread
import time
from time import mktime, sleep, strftime, strptime
from urllib import quote_plus
from urlparse import parse_qs, urlparse
try:
	import json
except ImportError:
    import simplejson as json

import gdata.calendar
import feedparser
from twisted.internet import reactor
from twisted.web.client import getPage

import bblib

def debug(msg):
	try:
		sys.stdout.write('%s\n' % msg)
		sys.stdout.flush()
	except:
		pass

class SignUpdater():
	thread_queue = []
	display_queue = []
	display_queue_curindex = 0
	last_queue_copy = -1

	def __init__(self):
		bblib.set_memory_config([
		bblib.FileConfig(bblib.TEXT_FILENAMES[0]),
		bblib.FileConfig(bblib.STRING_FILENAMES[0],
			bblib.FILE_TYPE_STRING)
		])
		bblib.set_text_file(bblib.TEXT_FILENAMES[0],
			'\x101', mode='hold')

	def _copy_new_messages(self):
		global QUEUE, QUEUE_LOCK, QUEUE_MTIME

		with QUEUE_LOCK:
			if QUEUE_MTIME <= self.last_queue_copy:
				return False

			new_msgs = False
			for msg in QUEUE:
				if msg not in self.thread_queue:
					self.thread_queue.append(msg)
					self.display_queue.append(msg)
					new_msgs = True
			for msg in self.thread_queue:
				if msg not in QUEUE:
					try:
						self.thread_queue.remove(msg)
						self.display_queue.remove(msg)
					except ValueError:
						# Might not be in display_queue, and we'll
						# be resilient re: thread_queue.
						pass

			self.last_queue_copy = QUEUE_MTIME

		return new_msgs

	def _get_new_messages(self):
		global NEW_MSG_QUICK_LOOP_AGE

		interrupted_by_new_msgs = \
			self.display_queue[self.display_queue_curindex:]
		new_msgs = self._copy_new_messages()

		if not new_msgs and \
		   self.display_queue_curindex < len(self.display_queue):
			return

		if new_msgs:
			if self.last_queue_copy > 0:
				# When new messages come in, display the most recent
				# non-permanent five messages the first time through.
				# Don't consider the first batch of messages on
				# startup to be "new."

				now = int(time.time())
				self.display_queue = []
				for msg in self.thread_queue:
					# Always insert interrupted messages if
					# they haven't been displayed yet.
					if msg in interrupted_by_new_msgs:
						if not msg.get('displayed', False):
							self.display_queue.append(msg)
						continue
					# Always display events happening now.
					if msg.get('when', now) <= now and \
					   msg.get('until', 0) >=  now:
						self.display_queue.append(msg)
						continue

					if 'perm' in msg.get('tags', []) and \
					   msg.get('displayed', False):
						continue
					if msg.get('when', now) + NEW_MSG_QUICK_LOOP_AGE < now:
						continue
					if msg.get('when', now) > now and \
					   'until' in msg:
						continue

					self.display_queue.append(msg)
				if not self.display_queue:
					self.display_queue = self.thread_queue[:5]
				self.display_queue_curindex = 0

			if interrupted_by_new_msgs:
				# If any interrupted messages are still valid, start
				# display_queue where we left off, so we don't starve the
				# newest messages when new messages arrive rapidly and
				# cause us to restart the display_queue loop each time.
				for msg in interrupted_by_new_msgs:
					try:
						self.display_queue_curindex = \
							self.display_queue.index(msg)
						break
					except ValueError:
						# The current message was removed from the
						# display_queue; keep trying to find one that's
						# left.
						pass
		else:
			# We've iterated over all messages; pull a copy of the
			# full queue in case we were displaying a shortened
			# queue because new messages arrived.
			self.display_queue = self.thread_queue[:]
			self.display_queue_curindex = 0

		debug('Display queue is now:')
		for msg in self.display_queue:
			debug('\t%s' % msg)

	def start(self):
		debug('Starting sign updater...')
		reactor.callLater(1, self.displayNextMessage)

	def displayNextMessage(self):
		global MSG_DISPLAY_TIME

		reactor.callLater(MSG_DISPLAY_TIME, self.displayNextMessage)

		if self.display_queue_curindex < len(self.display_queue):
			queue_item = self.display_queue[self.display_queue_curindex]
			queue_item['displayed'] = True

			debug('SIGN: %s' % queue_item['msg'])
			bblib.set_string_file('1', queue_item['msg'])

		self.display_queue_curindex += 1
		self._get_new_messages()

def replace_in_qs(url, attr, value):
	parsed_url = urlparse(url)

	qs_items = []
	for a, values in parse_qs(parsed_url.query).iteritems():
		if a == attr:
			continue
		for v in values:
			qs_items.append('%s=%s' % (a, v))
	qs_items.append('%s=%s' % (attr, quote_plus(str(value))))

	return '%s://%s%s?%s' % (
		parsed_url.scheme, parsed_url.netloc,
		parsed_url.path, '&'.join(qs_items),
	)

def get_url(url, success, err, headers={}):
	combined_headers = dict({
		'User-Agent': 'twitter2bbsign v2.0',
	}, **headers)

	debug('Fetching URL %s' % url)
	getPage(url, headers=combined_headers).addCallbacks(
		callback=success,
		callbackArgs=[url],
		errback=err,
		errbackArgs=[url, success, combined_headers])

def add_messages(new_msgs, replace=None):
	global QUEUE, QUEUE_LOCK, QUEUE_MTIME
	global QUEUE_FULL, QUEUE_UNDERFULL_LIFETIME, QUEUE_FULL_LIFETIME

	now = int(time.time())
	with QUEUE_LOCK:
		modified = False

		if replace:
			# Iterate over a copy of the queue since we'll be
			# removing items from it.
			for msg in QUEUE[:]:
				if replace in msg.get('tags', []):
					QUEUE.remove(msg)
					modified = True

		for msg in new_msgs:
			if msg not in QUEUE:
				QUEUE.append(msg)
				modified = True

		for msg in QUEUE[:]:
			# Never expire permanent messages.
			if 'perm' in msg.get('tags', []):
				continue

			if 'until' in msg:
				if now > msg['until']:
					QUEUE.remove(msg)
					modified = True
			elif 'when' in msg:
				# Don't count permanent messages against the queue size.
				queue_len = len([
					m
					for m
					 in QUEUE
					 if 'perm' not in m.get('perm', [])
				])

				if msg['when'] + QUEUE_UNDERFULL_LIFETIME <= now:
					QUEUE.remove(msg)
					modified = True
				elif queue_len > QUEUE_FULL and \
					msg['when'] + QUEUE_FULL_LIFETIME <= now:

					QUEUE.remove(msg)
					modified = True

		# All done; update QUEUE_MTIME to notify SignUpdater of changes.
		if modified:
			QUEUE.sort(lambda x, y: x.get('when', x.get('until', 0)) - \
				y.get('when', y.get('until', 0)))
			QUEUE_MTIME = now

			debug('QUEUE is now:')
			for msg in QUEUE:
				debug('\t%s' % msg)

def twitter_search_success(value, url):
	global TWITTER_POLL_INTERVAL, TWITTER_USER, TWITTER_PASS

	debug('Fetched Twitter search URL %s' % url)

	try:
		data = json.loads(value)
		url = str('http://search.twitter.com/search.json%s' %
			data['refresh_url'])
	except Exception, e:
		debug('Unable to parse Twitter search JSON response %s: %s' %
			(value, str(e)))
		data = {
			'results': [],
		}

	# Schedule the next poll as soon as possible, so any
	# problems below don't jeopardize future updates.
	reactor.callLater(TWITTER_POLL_INTERVAL, get_url,
		url, twitter_search_success, twitter_error)

	new_msgs = []
	for msg in data['results']:
		# We can't use \b in the leading part of the search since it
		# matches a non-word character followed immediately by a word
		# character. Since the '@' is in play, \b will never match.
		if re.search(r'(^|\W)@%s\b' % TWITTER_USER, msg['text']):
			new_msgs.append({
				'msg': '%s -> %s' % (msg['from_user'], msg['text']),
				'when': int(mktime(strptime(msg['created_at'],
					'%a, %d %b %Y %H:%M:%S +0000'))) - 14400,
				'tags': ['twitter_mention'],
			})

	add_messages(new_msgs)

def twitter_dm_success(value, url):
	global LAST_ID, TWITTER_POLL_INTERVAL, TWITTER_USER, TWITTER_PASS

	debug('Fetched Twitter direct message URL %s' % url)

	try:
		data = json.loads(value)
	except Exception, e:
		debug('Unable to parse Twitter direct message JSON response %s: %s' %
			(value, str(e)))
		data = []

	try:
		all_ids = [
			msg['id']
			for msg
			 in data
		]
		if all_ids:
			last_id = max(all_ids)
			if last_id > LAST_ID['direct']:
				LAST_ID['direct'] = last_id
				url = replace_in_qs(url,
					'since_id', LAST_ID['direct'])
	except Exception, e:
		debug('Unable to update since_id in Twitter direct message URL: %s' % str(e))

	# Schedule the next poll as soon as possible, so any
	# problems below don't jeopardize future updates.
	reactor.callLater(TWITTER_POLL_INTERVAL, get_url,
		url, twitter_dm_success, twitter_error,
		headers={
			'Authorization': 'Basic %s' %
				b64encode('%s:%s' % (TWITTER_USER, TWITTER_PASS)),
		})

	new_msgs = []
	for msg in data:
		new_msgs.append({
			'msg': '%s -> %s' % \
				(msg['sender']['screen_name'], msg['text']),
			'when': int(mktime(strptime(msg['created_at'],
				'%a %b %d %H:%M:%S +0000 %Y'))) - 14400,
			'tags': ['twitter_dm'],
		})

	add_messages(new_msgs)

def twitter_error(error, url, success_cb, headers):
	global TWITTER_POLL_INTERVAL

	debug('Problem polling Twitter URL %s, delaying for %d seconds, then attempting to solider on: %s' % \
		(url, TWITTER_POLL_INTERVAL * 4, error))
	reactor.callLater(TWITTER_POLL_INTERVAL * 4, get_url,
		url, success_cb, twitter_error, headers)

def gcal2timetuple(when):
	try:
		return strptime(when[:19], "%Y-%m-%dT%H:%M:%S")
	except:
		try:
			return strptime(when, "%Y-%m-%d")
		except:
			return None

def tz_offset():
	if time.daylight:
		offset = time.altzone / 60
	else:
		offset = time.timezone / 60

	if offset > 0:
		sign = '-'
	else:
		sign = '+'
		# '%02d' % -5 yields '-5', while '%02d' % 5 yields '05'
		offset = -offset

	return '%s%02d:%02d' % (sign, offset / 60, offset % 60)

def pretty_times(when, today_format="%H:%M", past_format="%d %b %H:%M",
                 future_format="%d %b %H:%M"):

	today = date.today()
	tomorrow = (today + timedelta(days=1)).timetuple()
	today = today.timetuple()

	start = gcal2timetuple(when.start_time)
	if start < today:
		start = strftime(past_format, start)
	elif start >= tomorrow:
		start = strftime(future_format, start)
	else:
		start = strftime(today_format, start)

	end = gcal2timetuple(when.end_time)
	if end < today:
		end = strftime(past_format, end)
	elif end >= tomorrow:
		end = strftime(future_format, end)
	else:
		end = strftime(today_format, end)

	return [start, end]

def gcal_success(value, url):
	global GCAL_POLL_INTERVAL

	debug('Fetched Google Calendar URL %s' % url)
		
	reactor.callLater(GCAL_POLL_INTERVAL, get_url,
		replace_in_qs(url, 'start-min',
			strftime('%%Y-%%m-%%dT%%H:00:00%s' % tz_offset())),
		gcal_success, gcal_error)

	new_msgs = []
	for event in gdata.calendar.CalendarEventFeedFromString(value).entry:
		# When an instance of a reccuring event is deleted, it
		# adds another event into feed.entry that does not have
		# an event.when. Skip these deleted events for now.
		if not event.when:
			continue

		for when in event.when:
			start_time, end_time = pretty_times(when,
				'today %H:%M', '%a %H:%M', '%a %H:%M')
			new_msgs.append({
				'msg': '%s: %s to %s' %
					(event.title.text[:38], start_time, end_time),
				'when': int(mktime(gcal2timetuple(when.start_time))),
				'until': int(mktime(gcal2timetuple(when.end_time))),
				'tags': ['gcal'],
			})

	add_messages(new_msgs, 'gcal')

def gcal_error(error, url, success_cb, headers):
	global GCAL_POLL_INTERVAL

	debug('Problem polling Google Calendar URL %s, delaying for %d seconds, then attempting to solider on: %s' % \
		(url, GCAL_POLL_INTERVAL * 4, error))
	reactor.callLater(GCAL_POLL_INTERVAL * 4, get_url,
		replace_in_qs(url, 'start-min',
			strftime('%%Y-%%m-%%dT%%H:00:00%s' % tz_offset())),
		success_cb, gcal_error)

def rss_success(value, url):
	global RSS_POLL_INTERVAL

	debug('Fetched RSS URL %s' % url)
		
	reactor.callLater(RSS_POLL_INTERVAL, get_url,
		url, rss_success, rss_error)

	entries = []
	for entry in feedparser.parse(value)['entries']:
		textonly = re.compile(r'^(.*?)<.*', re.S)
		entry = textonly.sub(r'\1', entry.summary).strip()
		entries.append(entry)

	add_messages([{
		'msg': entries[randrange(0, len(entries) - 1)],
		'when': int(time.time()),
		'tags': ['rss_%s' % url],
	}], 'rss_%s' % url)

def rss_error(error, url, success_cb, headers):
	global RSS_POLL_INTERVAL

	debug('Problem polling RSS URL %s, delaying for %d seconds, then attempting to solider on: %s' % \
		(url, RSS_POLL_INTERVAL * 4, error))
	reactor.callLater(RSS_POLL_INTERVAL * 4, get_url,
		url, success_cb, rss_error)

def load_state():
	global QUEUE, LAST_ID

	if not os.path.exists('state.pkl'):
		return

	fd = open('state.pkl', 'r')
	state = cPickle.load(fd)
	fd.close()

	QUEUE = state['queue']
	LAST_ID = state['last_id']

def save_state():
	global QUEUE, LAST_ID

	fd = open('state.pkl', 'w')
	state = {
		'queue': QUEUE,
		'last_id': LAST_ID,
	}
	cPickle.dump(state, fd)
	fd.close()

def shutdown():
	try:
		save_state()
	except Exception, e:
		print 'Unable to save state, exiting anyway: %s' % str(e)

if __name__ == '__main__':
	QUEUE = []
	QUEUE_LOCK = thread.allocate_lock()
	for msg in PERM_MSGS:
		QUEUE.append({
			'msg': msg,
			'tags': ['perm'],
		})
	LAST_ID = {
		'direct': 1,
	}

	try:
		load_state()
	except Exception, e:
		# The defaults, set above, will rule the day.
		print 'Unable to read saved state from state.pkl, starting from scratch: %s' % str(e)
	QUEUE_MTIME = 0

	reactor.addSystemEventTrigger('after', 'shutdown', shutdown)

	SignUpdater().start()

	get_url(
		'http://search.twitter.com/search.json?q=@%s&since_id=1' %
			TWITTER_USER,
		twitter_search_success, twitter_error)
	get_url('http://twitter.com/direct_messages.json?since_id=1',
		twitter_dm_success, twitter_error,
		headers={
			'Authorization': 'Basic %s' %
				b64encode('%s:%s' % (TWITTER_USER, TWITTER_PASS)),
		})
	get_url(
		replace_in_qs(GCAL_CALENDAR_URL,
			'start-min', strftime('%%Y-%%m-%%dT%%H:00:00%s' % tz_offset())),
		gcal_success, gcal_error)
	get_url('http://feeds.feedburner.com/tfln',
		rss_success, rss_error)

	reactor.run()
