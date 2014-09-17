# -*- coding: utf-8 -*-

import os
import logging
import re
import time
import calendar
import posixpath

logger = logging.getLogger(__name__)

from collections import deque
from urllib import unquote
from urlparse import urlparse, urljoin
from email.utils import formatdate, parsedate

from .utils import movefile
from .exceptions import *
from .parser import ThreadParser

import requests

class ThreadDownloader(object):
	# URL patterns
	CUP_4CHAN = r'(?:https?://)?([\w\.]+)/(\w+)/thread/(\d+)'
	CUP_OLD_4CHAN = r'(?:https?://)?([\w\.]+)/(\w+)/res/(\d+)'

	# A list of different splitters to try when attempting to get board and thread info from the URL
	CHAN_URL_PATTERNS = [
		CUP_4CHAN, # 4chan
		CUP_OLD_4CHAN, # mlpchan
		r'(?:https?://)?([\w\.]+)/(\w+)/thread/S?(\d+)', # archive.heinessen.com
		r'(?:https?://)?([\w\.]+)/chan/(\w+)/res/(\d+)', # Ponychan
		r'(?:https?://)?([\w\.]+)/(\w+)/(\d+)', # ylilauta
		r'(?:https?://)?([^/]+)(?:/.+?)?/(\w+)/res/(\d+)',
	]

	def __init__(self, thread_url, save_dir, save_filename, output_callback=None, progress_callback=None, cancel_callback=None):
		self.thread_url = thread_url

		self.download_extensions = set(['.ico', '.css', '.png', '.jpg', '.gif', '.webm'])

		if output_callback != None:
			self._output = output_callback

		if progress_callback != None:
			self._progress = progress_callback

		if cancel_callback != None:
			self._iscancelling = cancel_callback

		# Parse URL to determine if we need to give it any special treatment
		up = urlparse(self.thread_url)
		if up.netloc == 'boards.4chan.org':
			m = re.match(self.CUP_4CHAN, self.thread_url)
		elif up.netloc == 'mlpchan.net':
			m = re.match(self.CUP_OLD_4CHAN, self.thread_url)
		else:
			# Loop through the patterns until we get a match (or run out of patterns to try)
			for p in self.CHAN_URL_PATTERNS:
				m = re.match(p, self.thread_url)
				if m != None:
					break

		# If a match was found, proceed to extract information from it
		if m != None:
			self.site, self.board, self.thread_id = m.groups()
		else:
			raise UnsupportedSite

		self.set_destination(save_dir, save_filename)

		self._parser = None
		self.download_queue = deque()
		self.last_modified = None

	def set_destination(self, save_dir, save_filename=None, no_subdir=False):
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

	def _progress(self, prg, currentfile, filestotal, url):
		pass

	def _iscancelling(self):
		return False

	def download(self, force=False):
		# If destination directory has not yet been set, throw exception
		if self.save_dir == None:
			raise NoSaveDir

		try:
			headers = {}

			# Construct filename of original unmodified HTML
			originalfile = '{0:s}.original'.format(self.save_path)

			if self._parser == None:
				if os.path.isfile(originalfile):
					self.last_modified = formatdate(os.path.getmtime(originalfile))

				if os.path.isfile(self.save_path):
					self._parser = ThreadParser(self.thread_url, self.save_path, output_callback=self._output)
				else:
					self._parser = ThreadParser(self.thread_url, output_callback=self._output)

			if self.last_modified != None and not force:
				headers['If-Modified-Since'] = self.last_modified

			# Download page HTML
			tmpfile = '{0:s}.tmp'.format(self.save_path)
			try:
				headers = download_file(self.thread_url, tmpfile, headers = headers)
			except ThreadHTTPError as e:
				if e.code == 304:
					raise ThreadNotModified("Thread already up to date [{0:s}]".format(self.thread_url))
				elif e.code == 404:
					raise ThreadNotFound("Thread not found [{0:s}]".format(self.thread_url))
				else:
					raise

			# Parse new HTML file
			self._parser.update(tmpfile)

			for abslink, relpath in self._parser.links_found:
				path, filename = posixpath.split(relpath)
				saveto = os.path.join(self.save_dir, path, unquote(filename))

				# Get file extension
				ext = posixpath.splitext(filename)[1]

				# If link's extension is not in the list, skip it
				if ext not in self.download_extensions:
					logger.debug("File '{0:s}' is not in the list of extensions to download. Skipped.".format(filename))
					continue

				# If local file does not already exist, download it
				if os.path.isfile(saveto):
					logging.debug("File at {0:s} already exists locally. Skipped.".format(abslink))
					continue

				# Call new file event
				self._output("Link found [{0:s}]".format(abslink))

				self.download_queue.append((abslink, saveto))

			self._parser.links_found = []

			currentfile = 0
			filestotal = len(self.download_queue)

			def progress(url, read, size):
				if size > 0:
					prg = (float(read) / size) * 100
				else:
					prg = -1

				self._progress(prg, currentfile, filestotal, url)

			while len(self.download_queue) > 0:
				if self._iscancelling():
					raise CancelException

				url, saveto = self.download_queue.popleft()
				currentfile += 1

				try:
					try:
						download_file(url, saveto, progress_callback = progress)
					except ThreadHTTPError as e:
						if e.code == 404:
							# Skip non-existent files
							self._output("[{0:s}] was not found. Skipped.".format(url))
							continue
						else:
							raise
				except:
					self.download_queue.appendleft((url, saveto))
					raise

				self._output("[{0:s}] downloaded.".format(url))

			# Save modified HTML to file
			logger.info("Writing modified HTML to file: {0:s}...".format(self.save_path))

			self._parser.save(self.save_path)

			self.last_modified = headers['last-modified'] if 'last-modified' in headers else None

			# Rename temporary HTML file to original file
			movefile(tmpfile, originalfile)

			self._output("Thread [{0:s}] downloaded to [{1:s}]".format(self.thread_url, self.save_path))
		finally:
			pass

def download_file(url, saveto, headers=None, progress_callback=None):
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
		r = requests.get(url, stream=True, headers=headers)
		if r:
			if r.status_code == 304:
				raise ThreadHTTPError(url, r.status_code, r.reason)

			with open(saveto, 'wb') as f:
				read = 0

				if 'content-length' in r.headers:
					size = int(r.headers['content-length'])
				else:
					size = -1

				# Print initial progress report
				progress(url, read, size)

				try:
					# Iterate through the downloaded file content chunk by chunk and write it to file
					for chunk in r.iter_content(chunk_size=1024):
						if chunk:
							f.write(chunk)
							f.flush()

							read += len(chunk)

							# Report progress
							progress(url, read, size)
				except requests.RequestException as e:
					logger.error("RequestException downloading [{0:s}]: {1:s}", url, str(e))
					raise IncompleteDownload("Download incomplete [{0:s}]".format(url))

			if read < size:
				raise IncompleteDownload("Download incomplete [{0:s}]".format(url))

			if 'last-modified' in r.headers:
				try:
					os.utime(saveto, (time.time(), calendar.timegm(parsedate(r.headers['last-modified']))))
				except Exception as e:
					logger.warn("Failed to set modification times on [{0:s}]: {1:s}".format(saveto, e))

			return r.headers
		else:
			raise ThreadHTTPError(url, r.status_code, r.reason)
	except:
		if os.path.isfile(saveto):
			os.remove(saveto)

		raise
