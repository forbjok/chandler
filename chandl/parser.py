# -*- coding: utf-8 -*-

import os
import logging
import re
import posixpath

from urlparse import urlparse, urljoin

logger = logging.getLogger(__name__)

from bs4 import BeautifulSoup

from .exceptions import *
from .helpers import *
from .postprocess import *

RE_LINK_IS_FILE = re.compile(r'/.*?\.[^/]')

class ThreadParser(object):
	def __init__(self, url, filename=None, board_type=None, output_callback=None):
		self.thread_url = url
		self.thread_url_parseresult = urlparse(url)

		if output_callback != None:
			self._output = output_callback

		self.link_patterns = [
			re.compile('link.href'),
			re.compile('script.src'),
			re.compile('a.href'),
			re.compile('img.src'),
		]

		self.board_type = None
		self.merge = False
		self.helper_factory = ChanHelper
		self.postprocessor = NullPostProcessor()

		# If a board type was specified, set it
		if board_type != None:
			self._set_board_type(board_type)
		else:
			# Try to determine board type based on URL
			up = self.thread_url_parseresult
			if up.netloc == 'boards.4chan.org':
				self._set_board_type('4chan')
			elif up.netloc == 'mlpchan.net':
				self._set_board_type('mlpchan')

		self.links_local = {}
		self.links_found = []

		if filename == None:
			self._soup = None
		else:
			with open(filename) as f:
				self._soup = self._parse_html(f.read())

	def _output(self, text):
		pass

	def _set_board_type(self, n):
		if self.board_type != None:
			raise Exception("set_board_type() called more than once.")

		if n == '4chan':
			self.merge = True
		elif n == 'tinyboard':
			self.helper_factory = TinyboardChanHelper
			self.merge = True
		elif n == 'mlpchan':
			self.merge = True
			self.link_patterns.append(re.compile('img.data-mature-src'))
			self.postprocessor = MLPChanPostProcessor()
		else:
			self._output("Unknown board type '{0:s}'.".format(n))
			return

		self._output("Using board type '{0:s}'.".format(n))
		self.board_type = n

	def save(self, filename):
		try:
			soupstr = str(self._soup)
			with open(filename, 'wb') as f:
				f.write(soupstr)
		except:
			# If save failed, but file (probably empty) was created, remove it so it doesn't block attempts at re-downloading
			if os.path.isfile(filename):
				os.remove(filename)
			raise

	def update(self, filename):
		logger.info("Reading original HTML from file: {0:s}...".format(filename))
		with open(filename, 'rb') as f:
			html = f.read()

		# Parse new HTML
		newsoup = self._parse_html(html)

		# Attempt to merge with previous download, if applicable
		if self.merge and self._soup != None:
			newtags = self._merge(newsoup)
		else:
			self._soup = newsoup
			self.postprocessor.process_document(self._soup)
			newtags = [self._soup]

		# Find and process links
		for t in newtags:
			self._find_links(t)
			self.postprocessor.process_new_posts(newtags)

	def _merge(self, newsoup):
		logger.info("Merging...")

		# Get main helper
		try:
			helper = self._helper
		except AttributeError:
			self._helper = self.helper_factory(self._soup)
			helper = self._helper

		# Instantiate helper for the new thread
		newhelper = self.helper_factory(newsoup)

		# Get last post of main thread
		prevposts = helper.get_posts()
		newposts = newhelper.get_posts()
		previous_last_post_id = prevposts.keys()[-1]

		# Find first new post that also exists in the old thread,
		# taking into account that the last previous post may have been deleted
		while True:
			try:
				lpid, lp = prevposts.popitem()
			except KeyError:
				raise Exception("No common post could be found. This should not be possible, and should never happen.")

			if lpid in newposts:
				break

		last_shared_post_id = lpid

		# Get all new posts
		newposts = newhelper.get_posts_after(last_shared_post_id)
		count = len(newposts)

		# Insert new posts after previous last post
		helper.insert_posts_after(previous_last_post_id, newposts)

		self._output("{0:d} new posts merged.".format(count))

		return newposts

	def _handle(self, link):
		# Construct full link
		abslink = urljoin(self.thread_url, link)

		# If this link has already been handled, return it
		# No need to process the same link multiple times, as the result will always be the same
		if abslink in self.links_local:
			return self.links_local[abslink]

		# Construct local relative URL path
		o = urlparse(abslink)

		if len(o.fragment) > 0:
			orig = self.thread_url_parseresult
			if o.netloc == orig.netloc and o.path == orig.path:
				# If the URL contains a fragment and refers to the main html document,
				# drop the URL part as it isn't needed and will in all probability just cause the link to break
				return '#{0:s}'.format(o.fragment)

		if len(o.path) == 0 or not RE_LINK_IS_FILE.match(o.path):
			logger.debug("Link skipped - no path, or is not a file: {0:s}".format(abslink))
			return None

		# Construct relative path from URL components
		relpath = posixpath.join('files', o.netloc, o.path.lstrip('/'))

		self.links_local[abslink] = relpath
		self.links_found.append((abslink, relpath))
		return relpath

	def _find_links(self, soup):
		for tag in soup.find_all(True):
			for name, values in tag.attrs.items():
				if isinstance(values, basestring):
					values = [values]
				for v in values:
					matched = False

					# Check if tag/attribute/value matches any of the valid patterns
					matchstr = u'{tag:s}.{attr:s}={value:s}'.format(tag = tag.name, attr = name, value = v)

					for p in self.link_patterns:
						if p.match(matchstr) != None:
							# We found a match - doesn't matter if any other patterns match, so we break out of the loop
							matched = True
							break

					# If no patterns matched, move on to next value
					if not matched:
						continue

					newvalue = self._handle(v)
					if newvalue != None:
						tag[name] = newvalue

	def _parse_html(self, html):
		try:
			parser = self._html_parser
		except AttributeError:
			parser = select_html_parser(html)
			self._html_parser = parser

		logger.debug("Using HTML parser '{0:s}'.".format(parser))
		soup = BeautifulSoup(html, parser)

		if self.board_type == None and self._soup == None:
			bt = identify_board_type(soup)
			if bt != None:
				self.set_board_type(bt)

		return soup

def select_html_parser(html):
	if re.match(r'<!DOCTYPE HTML.*?(HTML 4\.01|XHTML 1\.0).*?>', html, re.IGNORECASE) != None:
		# Old XHTML or HTML 4 detected - use Python html parser
		return 'html.parser'

	# Since it wasn't old HTML, assume it is HTML5 - use html5lib
	return 'html5lib'

def identify_board_type(soup):
	if soup.find('a', {'href' : 'http://tinyboard.org/'}) != None:
		return 'tinyboard'

	return None
