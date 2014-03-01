# -*- coding: utf-8 -*-

import os
import logging
import posixpath
import re
import time
import calendar

logger = logging.getLogger(__name__)

from urllib import unquote
from urlparse import urlparse, urljoin
from email.utils import formatdate, parsedate

from .utils import movefile
from .exceptions import *
from .helpers import *
from .postprocess import *

import requests
from bs4 import BeautifulSoup

RE_LINK_IS_FILE = re.compile(r'/.*?\.[^/]')

class ThreadDownloader(object):
	# URL patterns
	CUP_4CHAN = r'(?:https?://)?([\w\.]+)/(\w+)/res/(\d+)'

	# A list of different splitters to try when attempting to get board and thread info from the URL
	CHAN_URL_PATTERNS = [
		CUP_4CHAN, # 4chan, mlpchan
		r'(?:https?://)?([\w\.]+)/(\w+)/thread/S?(\d+)', # archive.heinessen.com
		r'(?:https?://)?([\w\.]+)/chan/(\w+)/res/(\d+)', # Ponychan
		r'(?:https?://)?([\w\.]+)/(\w+)/(\d+)', # ylilauta
		r'(?:https?://)?([^/]+)(?:/.+?)?/(\w+)/res/(\d+)',
	]

	def __init__(self, document_url, save_dir, save_filename, output_callback = None, report_callback = None, cancel_callback = None):
		self.document_url = document_url
		self.document_url_parseresult = urlparse(self.document_url)

		if output_callback != None:
			self._output = output_callback

		if report_callback != None:
			self._report = report_callback

		if cancel_callback != None:
			self._iscancelling = cancel_callback

		self.link_patterns = [
			re.compile('link.href'),
			re.compile('script.src'),
			re.compile('a.href'),
			re.compile('img.src'),
		]

		self.download_extensions = set(['.ico', '.css', '.png', '.jpg', '.gif'])

		self.board_type = None
		self.merge = False
		self.helper_factory = ChanHelper
		self.postprocessor = NullPostProcessor()

		# Parse URL to determine if we need to give it any special treatment
		up = self.document_url_parseresult
		if up.netloc == 'boards.4chan.org':
			self.set_board_type('4chan')
			m = re.match(self.CUP_4CHAN, self.document_url)
		elif up.netloc == 'mlpchan.net':
			self.set_board_type('mlpchan')
			m = re.match(self.CUP_4CHAN, self.document_url)
		else:
			# Loop through the patterns until we get a match (or run out of patterns to try)
			for p in self.CHAN_URL_PATTERNS:
				m = re.match(p, self.document_url)
				if m != None:
					break

		# If a match was found, proceed to extract information from it
		if m != None:
			self.site, self.board, self.thread_id = m.groups()
		else:
			raise UnsupportedSite

		self.set_destination(save_dir, save_filename)

		self.downloaded_before = False
		self.links_local = {}
		self.last_modified = None

	def set_board_type(self, n):
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

	def set_destination(self, save_dir, save_filename = None, no_subdir = False):
		# If save_dir is None, set it to none and do no further processing - it will have to be set by the user later by calling set_destination() again
		if save_dir == None:
			self.save_dir = None
			return

		if no_subdir:
			self.save_dir = save_dir
		else:
			self.save_dir = os.path.join(save_dir, self.site, self.board, self.thread_id)

		self.save_filename = save_filename or '{0:s}.html'.format(self.thread_id)
		self.save_path = os.path.join(self.save_dir, self.save_filename)

		# If destination path does not exist, attempt to create it
		if not os.path.exists(self.save_dir):
			os.makedirs(self.save_dir)

	def _output(self, text):
		pass

	def _report(self, text):
		pass

	def _iscancelling(self):
		return False

	def _set_soup(self, soup):
		self.soup = soup
		self.helper = self.helper_factory(soup)

	def _merge(self, newsoup):
		try:
			soup = self.soup
		except AttributeError:
			self._set_soup(newsoup)
			return self.soup, [self.soup]

		logger.info("Merging...")

		# Get main helper
		helper = self.helper

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

		return soup, newposts

	def _handle(self, link):
		# Construct full link
		abslink = urljoin(self.document_url, link)

		# If this link has already been handled, return it
		# No need to process the same link multiple times, as the result will always be the same
		if abslink in self.links_local:
			return self.links_local[abslink]

		# Construct local relative URL path
		o = urlparse(abslink)

		if len(o.fragment) > 0:
			orig = self.document_url_parseresult
			if o.netloc == orig.netloc and o.path == orig.path:
				# If the URL contains a fragment and refers to the main html document,
				# drop the URL part as it isn't needed and will in all probability just cause the link to break
				return '#{0:s}'.format(o.fragment)

		if len(o.path) == 0 or not RE_LINK_IS_FILE.match(o.path):
			logger.debug("Link skipped - no path, or is not a file: {0:s}".format(abslink))
			return None

		# Construct relative path from URL components
		relpath = posixpath.join('files', o.netloc, o.path.lstrip('/'))

		path, filename = posixpath.split(relpath)
		savetodir = os.path.join(self.save_dir, path)
		savetofile = os.path.join(savetodir, unquote(filename))

		# Get file extension
		ext = posixpath.splitext(filename)[1]

		# If link's extension is not in the list, skip it
		if ext not in self.download_extensions:
			logger.debug("File '{0:s}' is not in the list of extensions to download. Skipped.".format(filename))
			return relpath

		# If local file does not already exist, download it
		if not os.path.isfile(savetofile):
			logging.debug("File at {0:s} does not exist locally. Download will be attempted.".format(abslink))
			# Call new file event
			self._output("Link found [{0:s}]".format(link))

			self.download_queue.append((abslink, savetofile))

		self.links_local[abslink] = relpath
		return relpath

	def _find_links(self, soup):
		for tag in soup.find_all(True):
			for name, values in tag.attrs.items():
				# Check if user (or calling script) wants to cancel and raise an exception if so
				if self._iscancelling():
					raise CancelException

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

		if self.board_type == None and not self.downloaded_before:
			bt = identify_board_type(soup)
			if bt != None:
				self.set_board_type(bt)

		return soup

	def download(self, force = False):
		# If destination directory has not yet been set, throw exception
		if self.save_dir == None:
			raise NoSaveDir

		self.download_queue = []

		try:
			headers = {}

			# Construct filename of original unmodified HTML
			originalfile = '{0:s}.original'.format(self.save_path)

			if not self.downloaded_before:
				if os.path.isfile(originalfile):
					self.last_modified = formatdate(os.path.getmtime(originalfile))

				if (self.merge or self.board_type) and os.path.isfile(self.save_path):
					with open(self.save_path) as f:
						oldsoup = self._parse_html(f.read())

					if self.merge:
						self._set_soup(oldsoup)
						self.downloaded_before = True

			if self.last_modified != None and not force:
				headers['If-Modified-Since'] = self.last_modified

			# Download page HTML
			tmpfile = '{0:s}.tmp'.format(self.save_path)
			try:
				headers = download_file(self.document_url, tmpfile, headers = headers)
			except ThreadHTTPError as e:
				if e.code == 304:
					raise ThreadNotModified("Thread already up to date [{0:s}]".format(self.document_url))
				elif e.code == 404:
					raise ThreadNotFound("Thread not found [{0:s}]".format(self.document_url))
				else:
					raise

			logger.info("Reading original HTML from file: {0:s}...".format(tmpfile))
			with open(tmpfile, 'rb') as f:
				html = f.read()

			# Process HTML
			logger.info("Processing HTML...")

			# Parse new HTML
			soup = self._parse_html(html)

			# Attempt to merge with previous download, if applicable
			if self.merge:
				soup, newtags = self._merge(soup)
			else:
				newtags = [soup]

			# Find and process links
			for t in newtags:
				self._find_links(t)
				self.postprocessor.process_new_posts(newtags)

			currentfile = 0
			filestotal = len(self.download_queue)

			rotator = "-\|/"
			def progress(url, read, size):
				if size > 0:
					prg = "{0: 3.0f}%".format((float(read) / size) * 100)
				else:
					prg = rotator[progress.rot]
					progress.rot += 1

					if progress.rot >= len(rotator):
						progress.rot = 0

				self._report("[{0:s}] Downloading file {1:d} of {2:d} [{3:s}]".format(prg, currentfile, filestotal, url))

			progress.rot = 0

			for url, saveto in self.download_queue:
				if self._iscancelling():
					raise CancelException

				currentfile += 1
				download_file(url, saveto, progress_callback = progress)
				self._output("[{0:s}] downloaded.".format(url))

			# If this is the first time downloading the main document, run document post-processing
			if not self.downloaded_before:
				logger.info("Post-processing...")
				self.postprocessor.process_document(soup)

			# Save modified HTML to file
			logger.info("Writing modified HTML to file: {0:s}...".format(self.save_path))
			try:
				soupstr = str(soup)
				with open(self.save_path, 'wb') as f:
					f.write(soupstr)
			except:
				# If save failed, but file (probably empty) was created, remove it so it doesn't block attempts at re-downloading
				if os.path.isfile(self.save_path):
					os.remove(self.save_path)
				raise
			else:
				self.downloaded_before = True
				self.last_modified = headers['last-modified'] if 'last-modified' in headers else None

				# Rename temporary HTML file to original file
				movefile(tmpfile, originalfile)

				self._output("Thread [{0:s}] downloaded to [{1:s}]".format(self.document_url, self.save_path))
		finally:
			pass

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

def download_file(url, saveto, headers = None, progress_callback = None):
	savetodir, savetofile = os.path.split(saveto)

	# If local directory does not exist, create it
	if not os.path.exists(savetodir):
		os.makedirs(savetodir)

	def progress(*args):
		if callable(progress_callback):
			progress_callback(*args)

	# Display progress before attempting to connect
	progress(url, 0, 0)

	# Attempt to download the new file
	try:
		r = requests.get(url, stream = True, headers = headers)
		if r:
			if r.status_code == 304:
				raise ThreadHTTPError(r.status_code, r.reason)

			with open(saveto, 'wb') as f:
				read = 0
				size = int(r.headers['content-length']) if 'content-length' in r.headers else -1

				progress(url, read, size)
				for chunk in r.iter_content(chunk_size = 1024):
					if chunk:
						f.write(chunk)
						f.flush()

						read += len(chunk)
						progress(url, read, size)

			if read < size:
				raise Exception("Download incomplete [{0:s}]".format(url))

			if 'last-modified' in r.headers:
				try:
					os.utime(saveto, (time.time(), calendar.timegm(parsedate(r.headers['last-modified']))))
				except Exception as e:
					logger.warn("Failed to set modification times on [{0:s}]: {1:s}".format(saveto, e))

			return r.headers
		else:
			raise ThreadHTTPError(r.status_code, r.reason)
	except:
		if os.path.isfile(saveto):
			os.remove(saveto)

		raise
