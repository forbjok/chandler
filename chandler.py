#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import sys
import os
import platform
import logging
import signal
import time
from optparse import OptionParser

from chandl import *

logger = logging.getLogger(__name__)

terminate = False

def signal_handler(signum, frame):
	global terminate
	terminate = True

signal.signal(signal.SIGINT, signal_handler)

def output(text):
	clear_line()
	print text

def cancel_callback():
	global terminate
	return terminate

def clear_line():
	if report.prev_length > 0:
		sys.stdout.write("\r{0:s}\r".format(' ' * report.prev_length))
		sys.stdout.flush()

		report.prev_length = 0

def report(text):
	if len(text) < report.prev_length:
		clear_line()

	sys.stdout.write("\r{0:s}".format(text))
	sys.stdout.flush()

	report.prev_length = len(text)

report.prev_length = 0

class ProcessAlreadyRunning(Exception):
	pass

class PID(object):
	def __init__(self, pidfile, ignore_pid = False):
		if platform.system() == 'Windows':
			logging.info("PID file not supported on Microsoft Windows.")
			self.pidfile = None
			return

		if os.path.isfile(pidfile):
			with open(pidfile) as f:
				pid = int(f.read())

			try:
				# Check if process is running
				os.kill(pid, 0)
				raise ProcessAlreadyRunning
			except OSError:
				pass

		self.pidfile = pidfile

	def __enter__(self):
		if self.pidfile == None:
			return

		with open(self.pidfile, 'w') as f:
			f.write(str(os.getpid()))

		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if self.pidfile == None:
			return

		os.remove(self.pidfile)

def main():
	global terminate

	# Parse commandline options
	op = OptionParser(usage = "%prog [options] <thread url>", version = "%prog 0.1.0")
	op.add_option('-d', '--destination-path', dest = 'destpath', default = None,
		help = "specify output path")
	op.add_option('-o', '--output', dest = 'output', default = None,
		help = "specify name of HTML file")
	op.add_option('', '--no-subfolder', dest = 'no_subfolder', default = False, action = 'store_true',
		help = "don't create a subfolder for each thread in the destination folder")
	op.add_option('-c', '--continuous', dest = 'continuous', default = False, action = 'store_true',
		help = "continuously re-download until 404 (will be ignored if multiple threads are specified)")
	op.add_option('-i', '--interval', dest = 'interval', type = 'float', default = 30,
		help = "number of seconds between checks (default: 30)")
	op.add_option('', '--auto-increment', dest = 'auto_increment', type = 'float', default = 5,
		help = "number of seconds to add per auto-increment (default: 5) (0 = disable)")
	op.add_option('', '--max-auto-increment', dest = 'max_auto_increment', type = 'float', default = 90,
		help = "maximum increase for auto-increment (default: 90)")
	op.add_option('-r', '--retry', dest = 'retry', type = 'int', default = 10,
		help = "number of times to retry (with increasing delay) on HTTP errors (excluding 404)")
	op.add_option('', '--retry-increment', dest = 'retry_increment', type = 'int', default = 120,
		help = "number of seconds to add for each failed check (default: 120)")
	op.add_option('-f', '--force', dest = 'force', default = False, action = 'store_true',
		help = "force re-download")
	op.add_option('', '--include-ext', dest = 'include_extensions', default = '',
		help = "semicolon-separated list of additional file extensions to download (ex: .js;.svg)")
	op.add_option('', '--no-merge', dest = 'nomerge', default = False, action = 'store_true',
		help = "force disable merging even if it is known to be supported for the site")
	op.add_option('', '--force-merge', dest = 'force_merge', default = False, action = 'store_true',
		help = "force enable merging even if the site is not known to be supported")
	op.add_option('-t', '--board-type', dest = 'board_type', default = None,
		help = "specify board type - should only be used for unsupported sites you know to be compatible with one of the existing board types (ie. any site using stock Tinyboard)")
	op.add_option('', '--ignore-pid', dest = 'ignore_pid', default = False, action = 'store_true',
		help = "ignore existing PID file. DO NOT USE THIS unless the PID checking somehow fails even though no process is running (ie. corrupt/invalid PID file)")
	op.add_option('-v', '--verbose', dest = 'verbose', default = False, action = 'store_true',
		help = "display more information on console")
	op.add_option('', '--debug', dest = 'debug', default = False, action = 'store_true',
		help = "display detailed debugging information")

	(opts, args) = op.parse_args()

	if len(args) < 1:
		op.print_help()
		return 1

	# Determine logging level based on commandline flags
	if opts.debug:
		level = logging.DEBUG
	elif opts.verbose:
		level = logging.INFO
	else:
		level = None

	# Initialize logging
	logging.basicConfig(level = level)

	if opts.continuous and len(args) > 1:
		output("More than one URL specified. Continuous flag will be ignored.")
		opts.continuous = False

	include_extensions = frozenset(opts.include_extensions.split(';'))

	for url in args:
		if terminate:
			break

		# Create downloader instance
		downloader = ThreadDownloader(url, None, None, output_callback = output, report_callback = report, cancel_callback = cancel_callback)

		# Set board type if specified
		if opts.board_type != None:
			downloader.set_board_type(opts.board_type)

		# If the user specified a destination path, use that. Otherwise create a directory matching the thread number in the current working directory.
		if opts.destpath != None:
			saveto = opts.destpath
		else:
			saveto = os.getcwd()

		downloader.set_destination(saveto, opts.output, no_subdir = opts.no_subfolder)

		if opts.nomerge:
			downloader.merge = False
		elif opts.force_merge:
			downloader.merge = True

		# Add included extensions to downloader's list of extensions
		downloader.download_extensions.update(include_extensions)

		try:
			with PID(os.path.join(downloader.save_dir, 'chandler.pid'), ignore_pid = opts.ignore_pid):
				run_downloader(downloader, opts)
		except ProcessAlreadyRunning:
			output("PID file exists and its process appears to be running. Terminating.")

	return 0

def run_downloader(downloader, opts):
	global terminate

	url = downloader.document_url

	# Define function for performing a download attempt
	def checkthread():
		report("Checking thread [{0:s}] for updates...".format(url))

		try:
			downloader.download(force = checkthread.force)
			checkthread.checks_since_last_update = 0
		except CancelException:
			output("Download cancelled. Thread has not been saved.")
			return False
		except ThreadNotModified as e:
			output(e)
			checkthread.checks_since_last_update += 1
		except ThreadNotFound as e:
			output(e)
			return False
		except (ThreadHTTPError, ConnectionError) as e:
			output(e)

			if checkthread.retry < opts.retry:
				checkthread.retry += 1
				return True

			return False
		finally:
			# Reset force after first run
			checkthread.force = False

			# Set last checked time
			checkthread.last_check = time.time()

		# Check succeeded, reset retry count
		checkthread.retry = 0
		return True

	# Set checkthread's force variable to the one specified by commandline (or false if unspecified)
	# Doing it this way is necessary because it is not possible to set a variable in an outer scope from inside a nested function
	checkthread.force = opts.force
	checkthread.retry = 0
	checkthread.last_check = None
	checkthread.checks_since_last_update = 0

	if opts.continuous:
		# Loop until a download attempt fails (or is canceled)
		while not terminate:
			# Check thread
			if not checkthread():
				break

			if checkthread.retry == 0:
				interval = opts.interval + min(opts.auto_increment * checkthread.checks_since_last_update, opts.max_auto_increment)
			else:
				interval = (opts.retry_increment * checkthread.retry)

			while not terminate:
				now = time.time()
				elapsed = now - checkthread.last_check
				remaining = interval - elapsed

				if remaining < 0:
					break

				if checkthread.retry == 0:
					report("Checking in {0:.0f}".format(remaining))
				else:
					report("Retrying ({1:d} of {2:d}) in {0:.0f}".format(remaining, checkthread.retry, opts.retry))

				try:
					time.sleep(1)
				except IOError:
					# User pressed CTRL-C, break loop
					output("User pressed CTRL-C. Terminating.")
					break
	else:
		# Just run download once
		checkthread()

if __name__ == '__main__':
	sys.exit(main())
